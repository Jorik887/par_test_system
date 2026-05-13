import asyncio
import logging
import struct
import time
import uuid
import xml.etree.ElementTree as ET
from contextlib import suppress
from typing import Any, Dict, Optional

from src.config.settings import settings
from src.services.targets import IshdConnectionConfig
from src.ishd.proto import (
    Ai_Common_pb2,
    Ai_Documents_pb2,
    Ai_Handshake_pb2,
    Ai_Parameters_pb2,
    Ai_Report_pb2,
    Ai_pb2,
)

logger = logging.getLogger(__name__)

class IshdError(Exception):
    """Base error for ISHD client"""

class IshdAuthError(IshdError):
    """Authentication error in ISHD"""

class IshdClient:
    def __init__(self, config: Optional[IshdConnectionConfig] = None) -> None:
        # Dlya sebya: vnutrenniy shag ISHD-klienta (init).
        cfg = config or IshdConnectionConfig(
            host=settings.ishd_host,
            port=settings.ishd_port,
            host_id=settings.ishd_host_id,
            software_name=settings.ishd_software_name,
            target_host_id=settings.ishd_target_host_id,
            target_host_ids=settings.ishd_target_host_ids,
            target_recipient=settings.ishd_target_recipient,
            default_port=settings.ishd_default_port,
            login=settings.ishd_login,
            password=settings.ishd_password,
            request_timeout_sec=settings.ishd_request_timeout_sec,
            doc_response_timeout_sec=settings.ishd_doc_response_timeout_sec,
            action_direct_timeout_sec=settings.ishd_action_direct_timeout_sec,
            action_result_timeout_sec=settings.ishd_action_result_timeout_sec,
        )

        self._host: str = cfg.host
        self._port: int = cfg.port
        self._host_id: str = cfg.host_id
        self._software_name: str = cfg.software_name
        self._target_recipient_raw: Optional[str] = cfg.target_recipient
        self._target_host_id_primary: str = cfg.target_host_id
        self._target_host_ids = [
            h.strip()
            for h in cfg.target_host_ids.split(",")
            if h.strip()
        ]
        if cfg.target_host_id and cfg.target_host_id not in self._target_host_ids:
            self._target_host_ids.append(cfg.target_host_id)
        self._login: Optional[str] = cfg.login
        self._password: Optional[str] = cfg.password
        self._request_timeout: float = cfg.request_timeout_sec
        self._doc_response_timeout: float = cfg.doc_response_timeout_sec
        self._action_direct_timeout: float = cfg.action_direct_timeout_sec
        self._action_result_timeout: float = cfg.action_result_timeout_sec

        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._reader_task: Optional[asyncio.Task[None]] = None
        
        self._pending: Dict[int, asyncio.Future] = {}
        self._pending_doc: Dict[bytes, asyncio.Queue] = {}
        self._pending_actions: Dict[bytes, asyncio.Queue] = {}
        self._target_machine_id: Optional[str] = None
        self._resolved_recipients: list[tuple[str, Optional[str]]] = []
        # Use a high starting id to reduce collisions with remote host message ids.
        self._msg_id: int = int(time.time() * 1000) & 0x7FFFFFFF

    def _is_connected(self) -> bool:
        # Dlya sebya: bystraya proverka zdorovya socketa pered otpravkoy.
        return self._writer is not None and not self._writer.is_closing()

    async def ensure_connected(self) -> None:
        # Dlya sebya: klient mozhet perepodklyuchit'sya mezhdu shagami avtoteesta.
        if self._is_connected():
            return
        await self.connect()

    def _fail_pending(self, reason: BaseException | str) -> None:
        # Dlya sebya: chtoby waitery ne viseli do timeout posle obryva transporta.
        message = str(reason).strip() or "Connection lost"

        pending = list(self._pending.values())
        pending_doc = list(self._pending_doc.values())
        pending_actions = list(self._pending_actions.values())

        self._pending.clear()
        self._pending_doc.clear()
        self._pending_actions.clear()

        for fut in pending:
            if fut.done():
                continue
            fut.set_exception(IshdError(message))

        for q in pending_doc:
            with suppress(Exception):
                q.put_nowait(IshdError(message))

        for q in pending_actions:
            with suppress(Exception):
                q.put_nowait(IshdError(message))

    def _drop_connection(self, reason: BaseException | str) -> tuple[Optional[asyncio.StreamWriter], Optional[asyncio.Task[None]]]:
        # Dlya sebya: odno mesto, gde помечаем socket poteryannym.
        writer = self._writer
        reader_task = self._reader_task
        self._writer = None
        self._reader = None
        self._reader_task = None
        self._fail_pending(reason)
        return writer, reader_task

    @staticmethod
    def _uuid_text_to_bytes(value: str) -> bytes:
        # Dlya sebya: vnutrenniy shag ISHD-klienta (uuid text to bytes).
        text = value.strip()
        if text and not text.startswith("{") and not text.endswith("}"):
            text = "{" + text + "}"
        return text.encode("utf-8")

    async def connect(self) -> None:
        # Dlya sebya: public shag po rabote s ISHD (connect).
        if self._is_connected():
            return
        if self._writer is not None or self._reader_task is not None:
            await self.close()
        logger.info("Connecting to ISHD %s:%s ...", self._host, self._port)
        connect_timeout = max(2.0, float(self._request_timeout))
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self._host, self._port),
            timeout=connect_timeout,
        )
        self._reader_task = asyncio.create_task(self._reader_loop())
        await self._handshake()
        await self._try_login()
        await self._resolve_target_machine_id()
        logger.info("ISHD handshake OK")

    async def close(self) -> None:
        # Dlya sebya: public shag po rabote s ISHD (close).
        if self._writer is None and self._reader_task is None:
            return
        writer, reader_task = self._drop_connection("Connection closed")
        if reader_task:
            reader_task.cancel()
        if writer is not None:
            with suppress(Exception):
                writer.close()
            with suppress(ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
                await writer.wait_closed()
        if reader_task:
            with suppress(asyncio.CancelledError, ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
                await reader_task

    async def disconnect(self) -> None:
        # Dlya sebya: public shag po rabote s ISHD (disconnect).
        await self.close()

    async def _handshake(self) -> None:
        # Dlya sebya: vnutrenniy shag ISHD-klienta (handshake).
        msg = Ai_pb2.HostMessage()
        msg.type = Ai_pb2.HostMessage.HANDSHAKE_REQUEST
        request = msg.handshake_request
        request.host_id = self._host_id
        version = Ai_Handshake_pb2.SoftwareVersion()
        version.protocol_version_current = (
            Ai_Handshake_pb2.SoftwareVersion.ProtocolCurrentVersion.CURRENT
        )
        version.protocol_version_min_supported = (
            Ai_Handshake_pb2.SoftwareVersion.ProtocolSupportedVersion.MIN
        )
        version.software_version = "1.0.0"
        version.software_name = self._software_name
        request.host_version.CopyFrom(version)

        response = await self._send_and_wait(msg)

        if response.type != Ai_pb2.HostMessage.HANDSHAKE_RESPONSE:
            raise IshdError(f"Unexpected response type on handshake: {response.type}")

    async def _send_and_wait(self, msg: Ai_pb2.HostMessage) -> Ai_pb2.HostMessage:
        # Dlya sebya: vnutrenniy shag ISHD-klienta (send and wait).
        await self.ensure_connected()
        msg_id = self._next_msg_id()
        msg.id = msg_id
        self._pending[msg_id] = asyncio.Future()
        await self._send(msg)
        fut = self._pending[msg_id]
        try:
            return await asyncio.wait_for(fut, timeout=self._request_timeout)
        except asyncio.TimeoutError:
            raise IshdError(f"Timeout waiting for response to message ID {msg_id}")
        finally:
            self._pending.pop(msg_id, None)

    async def _try_login(self) -> None:
        # Dlya sebya: vnutrenniy shag ISHD-klienta (try login).
        if not self._login or not self._password:
            return
        msg = Ai_pb2.HostMessage()
        msg.type = Ai_pb2.HostMessage.LOGIN_REQUEST
        msg.login_request.operation = Ai_Handshake_pb2.LoginOperation.LOGIN
        msg.login_request.login_params.login = self._login
        msg.login_request.login_params.password = self._password
        resp = await self._send_and_wait(msg)
        if resp.type != Ai_pb2.HostMessage.LOGIN_RESPONSE:
            raise IshdError(f"Unexpected response type on login: {resp.type}")
        if resp.login_response.report.code != Ai_Report_pb2.ReportCode.DONE:
            raise IshdAuthError(
                f"ISHD login failed: code={resp.login_response.report.code} "
                f"desc={resp.login_response.report.description}"
            )
        logger.info(
            "ISHD login response code=%s desc=%s",
            resp.login_response.report.code,
            resp.login_response.report.description,
        )

    def _next_msg_id(self) -> int:
        # Dlya sebya: vnutrenniy shag ISHD-klienta (next msg id).
        self._msg_id += 1
        return self._msg_id

    async def _send(self, msg: Ai_pb2.HostMessage) -> None:
        # Dlya sebya: vnutrenniy shag ISHD-klienta (send).
        if not self._is_connected():
            raise IshdError("Connection lost")
        payload = msg.SerializeToString()
        header = struct.pack("<I", len(payload))
        try:
            self._writer.write(header + payload)
            await self._writer.drain()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError) as e:
            writer, reader_task = self._drop_connection(f"Connection lost: {e}")
            if reader_task:
                reader_task.cancel()
            if writer is not None:
                with suppress(Exception):
                    writer.close()
                with suppress(ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
                    await writer.wait_closed()
            raise IshdError(f"Connection lost: {e}") from e

    async def send_paragraph_xml(
        self,
        *,
        alias: str,
        xml_body: str,
        doc_type: str = "paragraph_xml",
        accept_action: bool = False,
        capture_final_action: bool = False,
        final_action_timeout: Optional[float] = None,
        wait_non_system_response: bool = True,
    ) -> Any:
        # Dlya sebya: public shag po rabote s ISHD (send paragraph xml).
        # ISHD expects UUID bytes as string with braces, not raw 16-byte UUID.
        uuid_str = "{" + str(uuid.uuid4()) + "}"
        doc_id_bytes = uuid_str.encode("utf-8")
        doc_id = Ai_Common_pb2.UUID(data=doc_id_bytes)
        now_ms = int(time.time() * 1000)
        doc_time = Ai_Common_pb2.SystemTime(timestamp=now_ms)

        param_id = 0

        def next_param_id() -> int:
            # Dlya sebya: public shag po rabote s ISHD (next param id).
            nonlocal param_id
            param_id += 1
            return param_id

        def text_of(node: ET.Element) -> str:
            # Dlya sebya: public shag po rabote s ISHD (text of).
            return (node.text or "").strip()

        def as_bool(raw: Optional[str], *, default: bool = False) -> bool:
            # Dlya sebya: public shag po rabote s ISHD (as bool).
            if raw is None:
                return default
            return raw.strip().lower() in {"1", "true", "yes", "on"}

        def as_int(raw: Optional[str], *, default: int = 0) -> int:
            # Dlya sebya: public shag po rabote s ISHD (as int).
            if raw is None:
                return default
            try:
                return int(raw.strip())
            except (TypeError, ValueError):
                return default

        def as_float(raw: Optional[str], *, default: float = 0.0) -> float:
            # Dlya sebya: public shag po rabote s ISHD (as float).
            if raw is None:
                return default
            try:
                return float(raw.strip().replace(",", "."))
            except (TypeError, ValueError):
                return default

        def clamp_int32(value: int) -> int:
            # Dlya sebya: zashchita ot perepolneniya int32 pri razbore XML intervalov.
            if value < -2147483648:
                return -2147483648
            if value > 2147483647:
                return 2147483647
            return value

        def clamp_uint32(value: int) -> int:
            # Dlya sebya: zashchita ot otritsatelnykh i slishkom bolshikh znacheniy uint32.
            if value < 0:
                return 0
            if value > 4294967295:
                return 4294967295
            return value

        def is_param_tag(tag: str) -> bool:
            # Dlya sebya: public shag po rabote s ISHD (is param tag).
            return tag in {
                "text_field",
                "check_box",
                "combo_box",
                "spin_box",
                "group",
                "repeater",
                "date_time",
            }

        def fill_param_common(param: Ai_Parameters_pb2.Parameter, node: ET.Element) -> None:
            # Dlya sebya: public shag po rabote s ISHD (fill param common).
            param.id = next_param_id()
            param.name = node.get("name", "")
            param.alias = node.get("alias", "")
            required = as_bool(node.get("required"), default=False)
            param.required_param = required
            param.type_field.type = (
                Ai_Parameters_pb2.FormatParamField.RequiredField
                if required
                else Ai_Parameters_pb2.FormatParamField.SimpleField
            )

        def fill_element_from_xml(
            element: Ai_Parameters_pb2.OneOfParameters,
            node: ET.Element,
        ) -> None:
            # Dlya sebya: public shag po rabote s ISHD (fill element from xml).
            tag = node.tag
            if tag == "text_field":
                element.type = Ai_Parameters_pb2.OneOfParameters.TEXT_FIELD
                element.text_field.ui_type = (
                    Ai_Parameters_pb2.TextFieldParameter.MULTILINE
                    if node.get("type", "").lower() in {"multiline", "textarea"}
                    else Ai_Parameters_pb2.TextFieldParameter.SINGLELINE
                )
                element.text_field.text = text_of(node)
                max_symbols = as_int(node.get("max_symbols"), default=0)
                if max_symbols > 0:
                    element.text_field.max_symbols = max_symbols
                return

            if tag == "check_box":
                element.type = Ai_Parameters_pb2.OneOfParameters.CHECK_BOX
                checked = as_bool(node.get("checked"), default=as_bool(text_of(node), default=False))
                element.check_box.checked = checked
                element.check_box.text = text_of(node)
                return

            if tag == "combo_box":
                element.type = Ai_Parameters_pb2.OneOfParameters.COMBO_BOX
                ui_raw = node.get("type", "").lower()
                if ui_raw == "multiple":
                    element.combo_box.ui_type = Ai_Parameters_pb2.ComboBoxParameter.MULTIPLE
                elif ui_raw in {"radiobutton", "radio", "radio_button"}:
                    element.combo_box.ui_type = Ai_Parameters_pb2.ComboBoxParameter.RADIOBUTTON
                else:
                    element.combo_box.ui_type = Ai_Parameters_pb2.ComboBoxParameter.STANDARD

                values = [text_of(item) for item in node.findall("item") if text_of(item)]
                if values:
                    element.combo_box.values.extend(values)
                    selected = text_of(node)
                    if selected and selected in values:
                        element.combo_box.current_index.append(values.index(selected))
                current_attr = node.get("current")
                if current_attr is not None:
                    element.combo_box.current_index.append(as_int(current_attr, default=0))
                return

            if tag == "spin_box":
                element.type = Ai_Parameters_pb2.OneOfParameters.INTERVAL
                spin_type = node.get("type", "int").lower()
                value_raw = text_of(node)
                min_raw = as_int(node.get("min"), default=0)
                max_raw = as_int(node.get("max"), default=0)
                step_raw = as_int(node.get("step"), default=1)

                # Chast' sborok prisylaet huge uint granitsy bez type="uint".
                if spin_type not in {"uint", "double"} and min_raw >= 0 and max_raw > 2147483647:
                    spin_type = "uint"

                if spin_type == "uint":
                    interval_type = Ai_Parameters_pb2.ValueFromIntervalParameter.UINT
                    min_default = 0
                    max_default = 4294967295
                    value_int = clamp_uint32(as_int(value_raw, default=0))
                    element.interval.min_value.uint_value = clamp_uint32(
                        as_int(node.get("min"), default=min_default)
                    )
                    element.interval.max_value.uint_value = clamp_uint32(
                        as_int(node.get("max"), default=max_default)
                    )
                    element.interval.step.uint_value = max(clamp_uint32(step_raw), 1)
                    element.interval.value.uint_value = value_int
                elif spin_type == "double":
                    interval_type = Ai_Parameters_pb2.ValueFromIntervalParameter.DOUBLE
                    value_double = as_float(value_raw, default=0.0)
                    element.interval.min_value.double_value = as_float(node.get("min"), default=-1e9)
                    element.interval.max_value.double_value = as_float(node.get("max"), default=1e9)
                    element.interval.step.double_value = as_float(node.get("step"), default=0.01)
                    element.interval.value.double_value = value_double
                    precision = as_int(node.get("precision"), default=3)
                    if precision > 0:
                        element.interval.precision = precision
                else:
                    interval_type = Ai_Parameters_pb2.ValueFromIntervalParameter.INT
                    min_default = -2147483648
                    max_default = 2147483647
                    value_int = clamp_int32(as_int(value_raw, default=0))
                    element.interval.min_value.int_value = clamp_int32(
                        as_int(node.get("min"), default=min_default)
                    )
                    element.interval.max_value.int_value = clamp_int32(
                        as_int(node.get("max"), default=max_default)
                    )
                    step_value = clamp_int32(step_raw)
                    if step_value == 0:
                        step_value = 1
                    element.interval.step.int_value = step_value
                    element.interval.value.int_value = value_int

                element.interval.type = interval_type
                element.interval.ui_type = Ai_Parameters_pb2.ValueFromIntervalParameter.SPIN_BOX
                return

            if tag == "date_time":
                element.type = Ai_Parameters_pb2.OneOfParameters.DATE_TIME
                type_raw = node.get("type", "").lower()
                if type_raw == "date":
                    element.date_time.type = Ai_Parameters_pb2.DateTimeParameter.DATE
                elif type_raw == "time":
                    element.date_time.type = Ai_Parameters_pb2.DateTimeParameter.TIME
                else:
                    element.date_time.type = Ai_Parameters_pb2.DateTimeParameter.DATETIME
                element.date_time.time.timestamp = as_int(text_of(node), default=0)
                if node.get("mask"):
                    element.date_time.mask = node.get("mask", "")
                element.date_time.range = as_bool(node.get("range"), default=False)
                return

            if tag == "group":
                element.type = Ai_Parameters_pb2.OneOfParameters.GROUP
                for child in node:
                    if not is_param_tag(child.tag):
                        continue
                    child_param = build_param_from_xml(child)
                    if child_param is not None:
                        element.group.parameters.append(child_param)
                return

            if tag == "repeater":
                element.type = Ai_Parameters_pb2.OneOfParameters.REPEATER
                max_count = as_int(node.get("max_count"), default=0)
                if max_count > 0:
                    element.repeater.max_count = max_count

                children = [child for child in node if is_param_tag(child.tag)]
                if not children:
                    return

                # If repeater contains group nodes, each group is treated as a separate row.
                group_children = [child for child in children if child.tag == "group"]
                if group_children and len(group_children) == len(children):
                    for group_node in group_children:
                        item = element.repeater.data.add()
                        item.name = group_node.get("name", "")
                        for group_child in group_node:
                            if not is_param_tag(group_child.tag):
                                continue
                            item_param = build_param_from_xml(group_child)
                            if item_param is not None:
                                item.view.append(item_param)
                    if element.repeater.data:
                        first_item = element.repeater.data[0]
                        for item_param in first_item.view:
                            tmpl = element.repeater.template.add()
                            tmpl.CopyFrom(item_param)
                    return

                # Default: treat direct children as one repeater row.
                item = element.repeater.data.add()
                for child in children:
                    item_param = build_param_from_xml(child)
                    if item_param is not None:
                        item.view.append(item_param)
                        tmpl = element.repeater.template.add()
                        tmpl.CopyFrom(item_param)
                return

            # Unknown/unsupported control: keep a visible stub as text field for diagnostics.
            element.type = Ai_Parameters_pb2.OneOfParameters.TEXT_FIELD
            element.text_field.ui_type = Ai_Parameters_pb2.TextFieldParameter.SINGLELINE
            element.text_field.text = text_of(node)

        def build_param_from_xml(node: ET.Element) -> Optional[Ai_Parameters_pb2.Parameter]:
            # Dlya sebya: public shag po rabote s ISHD (build param from xml).
            if not is_param_tag(node.tag):
                return None
            param = Ai_Parameters_pb2.Parameter()
            fill_param_common(param, node)
            fill_element_from_xml(param.element, node)
            return param

        def build_state_from_xml(node: ET.Element) -> Optional[Ai_Documents_pb2.State]:
            # Dlya sebya: public shag po rabote s ISHD (build state from xml).
            if node.tag == "start_state":
                state_type = Ai_Documents_pb2.State.START
            elif node.tag == "state":
                state_type = Ai_Documents_pb2.State.DEFAULT
            elif node.tag == "final_state":
                state_type = Ai_Documents_pb2.State.FINAL
            else:
                return None

            state = Ai_Documents_pb2.State()
            state.type = state_type
            state.id = node.get("id", "")
            state.name = node.get("name", "")
            for action_node in node.findall("action"):
                action = state.actions.add()
                action.button = action_node.get("button", "")
                action.state = action_node.get("state", "")
                for action_param_node in action_node:
                    if not is_param_tag(action_param_node.tag):
                        continue
                    action_param = build_param_from_xml(action_param_node)
                    if action_param is not None:
                        action.items.append(action_param)
            return state

        root = None
        xml_alias = None
        xml_group = None
        xml_type = None
        try:
            root = ET.fromstring(xml_body)
            xml_alias = root.get("alias")
            xml_group = root.get("group")
            xml_type = root.get("type")
        except ET.ParseError:
            root = None

        effective_alias = xml_alias or alias
        effective_group = xml_group or "Пользовательские справочники"
        effective_type = xml_type or doc_type

        doc = Ai_Documents_pb2.Document(
            id=doc_id,
            type=effective_type,
            time=doc_time,
            group=effective_group,
            alias=effective_alias,
        )

        if root is not None:
            for node in root:
                if is_param_tag(node.tag):
                    param = build_param_from_xml(node)
                    if param is not None:
                        doc.items.append(param)
                elif node.tag in {"start_state", "state", "final_state"}:
                    state = build_state_from_xml(node)
                    if state is not None:
                        doc.states.append(state)

        # Fallback to minimal state machine if XML had no states.
        if not doc.states:
            start_state = Ai_Documents_pb2.State()
            start_state.type = Ai_Documents_pb2.State.Type.START
            start_state.id = "initial"
            start_state.name = "Принято"
            accept_action_def = Ai_Documents_pb2.Action()
            accept_action_def.button = "accept"
            accept_action_def.state = "accepted"
            start_state.actions.append(accept_action_def)
            doc.states.append(start_state)

            accepted_state = Ai_Documents_pb2.State()
            accepted_state.type = Ai_Documents_pb2.State.Type.DEFAULT
            accepted_state.id = "accepted"
            accepted_state.name = "Выполняется"
            doc.states.append(accepted_state)

        # Legacy fallback for non-Paragraph XML payloads.
        if not doc.items:
            param = Ai_Parameters_pb2.Parameter()
            param.id = next_param_id()
            param.name = "xml"
            param.alias = "xml"
            param.element.type = Ai_Parameters_pb2.OneOfParameters.TEXT_FIELD
            param.element.text_field.ui_type = Ai_Parameters_pb2.TextFieldParameter.SINGLELINE
            param.element.text_field.text = xml_body
            doc.items.append(param)

        # Route document to resolved recipients (similar to ESBMonitor behavior).
        explicit = self._target_recipient_raw
        recipients_for_log: list[str] = []

        def add_receiver(host_id: str, machine_id: Optional[str]) -> None:
            # Dlya sebya: public shag po rabote s ISHD (add receiver).
            receiver = Ai_Documents_pb2.Client()
            receiver.role = "executer"
            receiver_id = Ai_Common_pb2.UserId()
            receiver_id.hostId = host_id
            if machine_id:
                receiver_id.id.data = self._uuid_text_to_bytes(machine_id)
            receiver.id.CopyFrom(receiver_id)
            doc.clients.append(receiver)
            recipients_for_log.append(
                f"{machine_id}:{host_id}" if machine_id else host_id
            )

        if explicit and ":" in explicit:
            machine_id, host_id = explicit.rsplit(":", 1)
            add_receiver(host_id, machine_id)
        else:
            seen: set[str] = set()
            for host_id, machine_id in self._resolved_recipients:
                key = f"{machine_id}:{host_id}"
                if key in seen:
                    continue
                seen.add(key)
                add_receiver(host_id, machine_id)
            if not doc.clients:
                # Fallback for cold start / missing module list.
                add_receiver(self._target_host_id_primary, self._target_machine_id)

        edm = Ai_Documents_pb2.EdmMessage()
        edm.msg_type = Ai_Documents_pb2.EdmMessage.SEND_DOCUMENT_REQUEST
        edm.send_document_request.document.CopyFrom(doc)

        msg = Ai_pb2.HostMessage()
        msg.type = Ai_pb2.HostMessage.EDM_MESSAGE
        msg.edm_message.CopyFrom(edm)

        logger.info(
            "ISHD send_paragraph_xml alias=%s doc_id=%s sender=%s receiver=%s role=%s group=%s type=%s",
            effective_alias,
            uuid_str,
            self._host_id,
            ",".join(recipients_for_log),
            "executer",
            effective_group,
            effective_type,
        )

        try:
            resp = await self._send_and_wait(msg)
            if (
                resp.type == Ai_pb2.HostMessage.EDM_MESSAGE
                and resp.edm_message.msg_type == Ai_Documents_pb2.EdmMessage.DOCUMENT_RESPONSE
            ):
                doc_resp = resp.edm_message.document_response
                if doc_resp.system_response:
                    if wait_non_system_response:
                        # Wait for business response from Paragraph, not only transport/system ACK.
                        doc_resp = await self._await_document_response(
                            doc_id_bytes,
                            timeout=self._doc_response_timeout,
                            require_non_system=True,
                        )
            else:
                # Some ISHD setups echo SEND_DOCUMENT_REQUEST first. Wait for response.
                doc_resp = await self._await_document_response(
                    doc_id_bytes,
                    timeout=self._doc_response_timeout,
                    require_non_system=wait_non_system_response,
                )

            logger.info(
                "ISHD document_response doc_id=%s code=%s desc=%s",
                uuid_str,
                doc_resp.report.code,
                doc_resp.report.description,
            )

            # If Paragraph/ISHD already rejected the document, stop here.
            if doc_resp.report.code != Ai_Report_pb2.ReportCode.DONE:
                return doc_resp

            if not accept_action:
                return doc_resp

            action_wait_timeout = final_action_timeout
            if action_wait_timeout is None:
                action_wait_timeout = self._action_result_timeout
            try:
                action_wait_timeout = float(action_wait_timeout)
            except (TypeError, ValueError):
                action_wait_timeout = self._action_result_timeout
            action_wait_timeout = max(self._action_direct_timeout, action_wait_timeout)

            action_resp = await self._send_action_accept(
                doc_id_bytes,
                timeout=action_wait_timeout,
            )
            logger.info(
                "ISHD action_response doc_id=%s code=%s desc=%s",
                uuid_str,
                action_resp.report.code,
                action_resp.report.description,
            )
            if capture_final_action:
                # Dlya sebya: final action mojet priyti pozje transport ACK.
                # Berem bolee terpelivyy timeout, chtoby ne dat' lozhnoye "ok".
                wait_final_timeout = final_action_timeout
                if wait_final_timeout is None:
                    wait_final_timeout = max(self._action_result_timeout, self._doc_response_timeout)
                final_action = await self._await_final_action_request(
                    doc_id_bytes,
                    timeout=wait_final_timeout,
                )
                return action_resp, final_action
            return action_resp
        finally:
            self._pending_doc.pop(doc_id_bytes, None)
            self._pending_actions.pop(doc_id_bytes, None)

    async def _await_final_action_request(
        self,
        doc_id_bytes: bytes,
        *,
        timeout: Optional[float] = None,
        final_states: Optional[set[str]] = None,
    ) -> Optional[Ai_Documents_pb2.SendActionRequest]:
        # Dlya sebya: vnutrenniy shag ISHD-klienta (await final action request).
        q = self._pending_actions.get(doc_id_bytes)
        if q is None:
            q = asyncio.Queue()
            self._pending_actions[doc_id_bytes] = q

        states = {s.lower() for s in (final_states or {"completed", "failed"})}
        wait_timeout = timeout if timeout is not None else self._action_result_timeout
        deadline = time.monotonic() + wait_timeout
        last_request: Optional[Ai_Documents_pb2.SendActionRequest] = None

        while True:
            remain = deadline - time.monotonic()
            if remain <= 0:
                return last_request
            try:
                queued = await asyncio.wait_for(q.get(), timeout=remain)
            except asyncio.TimeoutError:
                return last_request
            if isinstance(queued, BaseException):
                raise IshdError(str(queued))

            _, action_request = queued

            last_request = action_request
            state = (action_request.action.state or "").strip().lower()
            if not states or state in states:
                return action_request

    async def _await_document_response(
        self,
        doc_id_bytes: bytes,
        timeout: int = 10,
        require_non_system: bool = False,
        allow_system_fallback_on_timeout: bool = False,
    ) -> Ai_Documents_pb2.DocumentResponse:
        # Dlya sebya: vnutrenniy shag ISHD-klienta (await document response).
        q = self._pending_doc.get(doc_id_bytes)
        if q is None:
            q = asyncio.Queue()
            self._pending_doc[doc_id_bytes] = q

        last_system_resp: Optional[Ai_Documents_pb2.DocumentResponse] = None
        deadline = time.monotonic() + timeout
        while True:
            remain = deadline - time.monotonic()
            if remain <= 0:
                if (
                    require_non_system
                    and allow_system_fallback_on_timeout
                    and last_system_resp is not None
                ):
                    logger.warning(
                        "ISHD timeout waiting non-system DOCUMENT_RESPONSE; "
                        "falling back to system response code=%s desc=%s",
                        last_system_resp.report.code,
                        last_system_resp.report.description,
                    )
                    return last_system_resp
                if require_non_system:
                    raise IshdError("Timeout waiting for non-system DOCUMENT_RESPONSE")
                raise IshdError("Timeout waiting for DOCUMENT_RESPONSE")
            try:
                resp = await asyncio.wait_for(q.get(), timeout=remain)
            except asyncio.TimeoutError:
                if (
                    require_non_system
                    and allow_system_fallback_on_timeout
                    and last_system_resp is not None
                ):
                    logger.warning(
                        "ISHD timeout waiting non-system DOCUMENT_RESPONSE; "
                        "falling back to system response code=%s desc=%s",
                        last_system_resp.report.code,
                        last_system_resp.report.description,
                    )
                    return last_system_resp
                if require_non_system:
                    raise IshdError("Timeout waiting for non-system DOCUMENT_RESPONSE")
                raise IshdError("Timeout waiting for DOCUMENT_RESPONSE")
            if isinstance(resp, BaseException):
                raise IshdError(str(resp))
            if require_non_system and resp.system_response:
                last_system_resp = resp
                continue
            if not require_non_system or not resp.system_response:
                return resp

    async def _send_action_accept(
        self,
        doc_id_bytes: bytes,
        *,
        timeout: Optional[float] = None,
    ) -> Ai_Documents_pb2.DocumentResponse:
        # Dlya sebya: vnutrenniy shag ISHD-klienta (send action accept).
        await self.ensure_connected()
        action = Ai_Documents_pb2.Action()
        action.button = "accept"
        action.state = "accepted"

        action_req = Ai_Documents_pb2.SendActionRequest()
        action_req.id.CopyFrom(Ai_Common_pb2.UUID(data=doc_id_bytes))
        action_req.action.CopyFrom(action)

        edm = Ai_Documents_pb2.EdmMessage()
        edm.msg_type = Ai_Documents_pb2.EdmMessage.SEND_ACTION_REQUEST
        edm.send_action_request.CopyFrom(action_req)

        msg = Ai_pb2.HostMessage()
        msg.type = Ai_pb2.HostMessage.EDM_MESSAGE
        msg.edm_message.CopyFrom(edm)

        msg_id = self._next_msg_id()
        msg.id = msg_id
        self._pending[msg_id] = asyncio.Future()
        await self._send(msg)
        fut = self._pending[msg_id]
        try:
            # For SEND_ACTION_REQUEST some ISHD setups do not return direct response by msg id.
            resp = await asyncio.wait_for(fut, timeout=self._action_direct_timeout)
            if (
                resp.type == Ai_pb2.HostMessage.EDM_MESSAGE
                and resp.edm_message.msg_type == Ai_Documents_pb2.EdmMessage.DOCUMENT_RESPONSE
                and not resp.edm_message.document_response.system_response
            ):
                return resp.edm_message.document_response
        except asyncio.TimeoutError:
            logger.info(
                "ISHD no direct host response for SEND_ACTION_REQUEST msg_id=%s; waiting document response",
                msg_id,
            )
        finally:
            self._pending.pop(msg_id, None)

        return await self._await_document_response(
            doc_id_bytes,
            timeout=(timeout if timeout is not None else self._action_result_timeout),
            require_non_system=True,
            allow_system_fallback_on_timeout=True,
        )

    async def send_xml_over_ishd(self, xml_text: str) -> dict:
        # Dlya sebya: public shag po rabote s ISHD (send xml over ishd).
        try:
            response = await self.send_paragraph_xml(alias="paragraph_xml", xml_body=xml_text)
            return {"status": "ok", "data": response}
        except Exception as e:
            return {"status": "fail", "message": str(e)}

    async def request_module_list(self) -> Ai_pb2.HostMessage:
        # Dlya sebya: public shag po rabote s ISHD (request module list).
        msg = Ai_pb2.HostMessage()
        msg.type = Ai_pb2.HostMessage.MODULE_LIST_REQUEST
        msg.module_list_request.SetInParent()
        return await self._send_and_wait(msg)

    async def _resolve_target_machine_id(self) -> None:
        # Dlya sebya: vnutrenniy shag ISHD-klienta (resolve target machine id).
        explicit = (self._target_recipient_raw or "").strip()
        if explicit and ":" in explicit:
            machine_id, host_id = explicit.rsplit(":", 1)
            machine_id = machine_id.strip()
            host_id = host_id.strip()
            if machine_id and host_id:
                self._resolved_recipients = [(host_id, machine_id)]
                self._target_machine_id = (
                    machine_id if host_id == self._target_host_id_primary else None
                )
                logger.info(
                    "ISHD explicit recipient override host=%s machine_id=%s",
                    host_id,
                    machine_id,
                )
                return

        target_hosts = self._target_host_ids or [self._target_host_id_primary]
        try:
            msg = await self.request_module_list()
        except Exception as e:
            logger.warning("ISHD failed to resolve target machine id: %s", e)
            return
        if msg.type != Ai_pb2.HostMessage.MODULE_LIST_RESPONSE:
            return
        candidates: Dict[str, Dict[str, Optional[str]]] = {
            host: {
                "auth_local": None,
                "auth": None,
                "online_local": None,
                "online": None,
                "any_local": None,
                "any": None,
            }
            for host in target_hosts
        }
        host_norm = str(self._host or "").strip().lower()
        host_is_loopback = host_norm in {"127.0.0.1", "localhost", "::1"}
        for machine in msg.module_list_response.list:
            machine_id = str(machine.machine_id or "").strip()
            machine_localhost = bool(getattr(machine, "localhost", False))
            machine_ip = str(getattr(machine, "ip_address", "") or "").strip().lower()
            machine_name = str(getattr(machine, "machine_name", "") or "").strip().lower()
            local_match = bool(
                machine_localhost
                if host_is_loopback
                else (
                    (machine_ip and machine_ip == host_norm)
                    or (machine_name and machine_name == host_norm)
                )
            )
            for module in machine.modules:
                if module.id not in candidates:
                    continue
                logger.info(
                    "ISHD target module candidate host=%s machine_id=%s online=%s authorized=%s localhost=%s ip=%s alias=%s",
                    module.id,
                    machine_id,
                    getattr(module, "online", None),
                    getattr(module, "authorized", None),
                    machine_localhost,
                    machine_ip,
                    getattr(module, "alias_id", ""),
                )
                st = candidates[module.id]
                if st["any"] is None:
                    st["any"] = machine_id
                if local_match and st["any_local"] is None:
                    st["any_local"] = machine_id
                if bool(getattr(module, "online", False)) and st["online"] is None:
                    st["online"] = machine_id
                if (
                    local_match
                    and bool(getattr(module, "online", False))
                    and st["online_local"] is None
                ):
                    st["online_local"] = machine_id
                if (
                    bool(getattr(module, "online", False))
                    and bool(getattr(module, "authorized", False))
                    and st["auth"] is None
                ):
                    st["auth"] = machine_id
                if (
                    local_match
                    and bool(getattr(module, "online", False))
                    and bool(getattr(module, "authorized", False))
                    and st["auth_local"] is None
                ):
                    st["auth_local"] = machine_id

        self._resolved_recipients = []
        for host in target_hosts:
            st = candidates[host]
            chosen = (
                st["auth_local"]
                or st["auth"]
                or st["online_local"]
                or st["online"]
                or st["any_local"]
                or st["any"]
            )
            if chosen:
                self._resolved_recipients.append((host, chosen))
                if st["auth_local"]:
                    logger.info(
                        "ISHD resolved recipient host=%s machine_id=%s (authorized local match)",
                        host,
                        chosen,
                    )
                elif st["auth"]:
                    logger.info("ISHD resolved recipient host=%s machine_id=%s", host, chosen)
                elif st["online_local"]:
                    logger.warning(
                        "ISHD target host online local match but not authorized; fallback host=%s machine_id=%s",
                        host,
                        chosen,
                    )
                elif st["online"]:
                    logger.warning(
                        "ISHD target host online but not authorized; fallback host=%s machine_id=%s",
                        host,
                        chosen,
                    )
                else:
                    logger.warning(
                        "ISHD target host unavailable; fallback to last seen host=%s machine_id=%s",
                        host,
                        chosen,
                    )
            else:
                logger.warning("ISHD target host not found in module list: %s", host)

        # Keep legacy single target for compatibility paths.
        self._target_machine_id = None
        for host, machine_id in self._resolved_recipients:
            if host == self._target_host_id_primary:
                self._target_machine_id = machine_id
                break

    async def _reader_loop(self) -> None:
        # Dlya sebya: vnutrenniy shag ISHD-klienta (reader loop).
        while True:
            try:
                header = await self._reader.readexactly(4)
                if not header:
                    break
                (size,) = struct.unpack("<I", header)
                payload = await self._reader.readexactly(size)
                msg = Ai_pb2.HostMessage()
                msg.ParseFromString(payload)

                if msg.type == Ai_pb2.HostMessage.EDM_MESSAGE:
                    logger.info(
                        "ISHD incoming EDM host_msg_id=%s edm_type=%s",
                        msg.id,
                        msg.edm_message.msg_type,
                    )
                    self._log_incoming_edm(msg)

                if (
                    msg.type == Ai_pb2.HostMessage.EDM_MESSAGE
                    and msg.edm_message.msg_type == Ai_Documents_pb2.EdmMessage.DOCUMENT_RESPONSE
                ):
                    doc_id_bytes = msg.edm_message.document_response.id.data
                    q = self._pending_doc.get(doc_id_bytes)
                    if q is not None:
                        q.put_nowait(msg.edm_message.document_response)
                        continue

                if (
                    msg.type == Ai_pb2.HostMessage.EDM_MESSAGE
                    and msg.edm_message.msg_type == Ai_Documents_pb2.EdmMessage.SEND_DOCUMENT_REQUEST
                ):
                    await self._send_incoming_document_response(
                        ref_id=msg.id,
                        doc_id=msg.edm_message.send_document_request.document.id,
                        code=Ai_Report_pb2.ReportCode.DONE,
                        description="incoming document ack",
                    )

                if (
                    msg.type == Ai_pb2.HostMessage.EDM_MESSAGE
                    and msg.edm_message.msg_type == Ai_Documents_pb2.EdmMessage.SEND_ACTION_REQUEST
                ):
                    doc_id_bytes = msg.edm_message.send_action_request.id.data
                    # Always ACK incoming action requests so remote workflow can continue.
                    await self._send_incoming_document_response(
                        ref_id=msg.id,
                        doc_id=msg.edm_message.send_action_request.id,
                        code=Ai_Report_pb2.ReportCode.DONE,
                        description="incoming action ack",
                    )
                    aq = self._pending_actions.get(doc_id_bytes)
                    if aq is None:
                        aq = asyncio.Queue()
                        self._pending_actions[doc_id_bytes] = aq
                    aq.put_nowait((msg.id, msg.edm_message.send_action_request))

                fut = self._pending.get(msg.id)
                if fut and not fut.done():
                    fut.set_result(msg)
                else:
                    logger.info("Received ISHD message id=%s type=%s", msg.id, msg.type)
            except asyncio.IncompleteReadError:
                self._drop_connection("Connection lost")
                break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error reading from ISHD: {e}")
                self._drop_connection(f"Connection lost: {e}")
                break

    def _log_incoming_edm(self, msg: Ai_pb2.HostMessage) -> None:
        # Dlya sebya: vnutrenniy shag ISHD-klienta (log incoming edm).
        edm_type = msg.edm_message.msg_type
        if edm_type == Ai_Documents_pb2.EdmMessage.SEND_DOCUMENT_REQUEST:
            incoming_doc = msg.edm_message.send_document_request.document
            logger.info(
                "ISHD incoming SEND_DOCUMENT_REQUEST alias=%s group=%s type=%s",
                incoming_doc.alias,
                incoming_doc.group,
                incoming_doc.type,
            )
        elif edm_type == Ai_Documents_pb2.EdmMessage.SEND_ACTION_REQUEST:
            incoming_action = msg.edm_message.send_action_request
            logger.info(
                "ISHD incoming SEND_ACTION_REQUEST doc_id=%s button=%s state=%s",
                incoming_action.id.data.decode("utf-8", errors="ignore"),
                incoming_action.action.button,
                incoming_action.action.state,
            )

    async def _send_incoming_document_response(
        self,
        *,
        ref_id: int,
        doc_id: Ai_Common_pb2.UUID,
        code: int,
        description: str,
    ) -> None:
        # Dlya sebya: vnutrenniy shag ISHD-klienta (send incoming document response).
        report = Ai_Report_pb2.Report(code=code, description=description)
        doc_resp = Ai_Documents_pb2.DocumentResponse()
        doc_resp.id.CopyFrom(doc_id)
        doc_resp.report.CopyFrom(report)

        edm = Ai_Documents_pb2.EdmMessage()
        edm.msg_type = Ai_Documents_pb2.EdmMessage.DOCUMENT_RESPONSE
        edm.document_response.CopyFrom(doc_resp)

        out = Ai_pb2.HostMessage()
        out.type = Ai_pb2.HostMessage.EDM_MESSAGE
        out.id = ref_id
        out.edm_message.CopyFrom(edm)
        await self._send(out)

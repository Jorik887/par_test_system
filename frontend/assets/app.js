const DEFAULT_API_BASE =
  (typeof window !== "undefined" && window.location && /^https?:/i.test(window.location.origin))
    ? window.location.origin
    : "http://127.0.0.1:8000";
const API_BASE_KEY = "par_test_api_base";
const TARGET_ID_KEY = "par_test_target_id";
const FILTER_CONDITIONS = ["Равно", "Не равно", "Больше", "Не больше", "Меньше", "Не меньше", "Содержит"];
const DEFAULT_FILTER_CONDITION = "Равно";
const REQUEST_TIMEOUT_MS = 60000;
const RETRYABLE_HTTP_STATUSES = new Set([502, 503, 504]);
const PROFILE_PROBE_ISHD_WAIT_MS = 120000;
const PROFILE_PROBE_RETRY_MS = 2000;
const PROFILE_PROBE_BG_WAIT_MS = 60000;
const PROFILE_PROBE_BG_RETRY_MS = 2000;
const PERF_MAX_ITEMS = 500;
const buttonStateTimers = new WeakMap();

const state = {
  apiBase: DEFAULT_API_BASE,
  targetId: null,
  targets: [],
  selectedRowId: "",
  searchRows: [],
  searchColumns: [],
  searchRowIds: [],
  insertColumns: [],
  insertRows: [],
  createColumnTypes: [],
  createSeedRows: [],
  autoReports: [],
  autoCurrentReport: null,
  autoRunInFlight: false,
  autoRunStartedAtMs: null,
  autoRunTimerId: null,
  autoRunJobId: "",
  autoRunPollTimerId: null,
  autoRunPollInFlight: false,
  autoOpenReportInFlight: false,
  autoLastOpenedRunId: null,
  autoDictsLoadInFlight: false,
  autoSelectedRunId: "",
  autoArtifactsDownloadedRunId: "",
  ishdProbeAutoRunning: false,
  ishdProbeAutoToken: 0,
  perfUiActions: [],
  perfApiCalls: [],
};

const el = {};

document.addEventListener("DOMContentLoaded", () => {
  startMojibakeAutoRepair();
  bindElements();
  setupNavigation();
  setupConnectionBar();
  setupTargets();
  setupUserDicts();
  setupDictsRest();
  setupParagraphSection();
  hydrateApiBase();
  bootstrapPage();
});

function bindElements() {
  el.menuButtons = Array.from(document.querySelectorAll(".menu-btn"));
  el.sections = Array.from(document.querySelectorAll(".section"));
  el.toast = document.getElementById("toast");

  el.apiBase = document.getElementById("apiBase");
  el.targetSelect = document.getElementById("targetSelect");
  el.quickParagraphLogin = document.getElementById("quickParagraphLogin");
  el.quickParagraphPassword = document.getElementById("quickParagraphPassword");
  el.targetReloadBtn = document.getElementById("targetReloadBtn");
  el.targetAutoCurrentBtn = document.getElementById("targetAutoCurrentBtn");
  el.saveApiBase = document.getElementById("saveApiBase");
  el.pingApi = document.getElementById("pingApi");

  el.targetsTable = document.getElementById("targetsTable");
  el.targetEditId = document.getElementById("targetEditId");
  el.targetName = document.getElementById("targetName");
  el.targetDescription = document.getElementById("targetDescription");
  el.targetIshdHost = document.getElementById("targetIshdHost");
  el.targetIshdPort = document.getElementById("targetIshdPort");
  el.targetIshdHostId = document.getElementById("targetIshdHostId");
  el.targetIshdSoftwareName = document.getElementById("targetIshdSoftwareName");
  el.targetIshdLogin = document.getElementById("targetIshdLogin");
  el.targetIshdPassword = document.getElementById("targetIshdPassword");
  el.targetHostIds = document.getElementById("targetHostIds");
  el.targetRestBase = document.getElementById("targetRestBase");
  el.targetParagraphDsn = document.getElementById("targetParagraphDsn");
  el.targetCreateBtn = document.getElementById("targetCreateBtn");
  el.targetUpdateBtn = document.getElementById("targetUpdateBtn");
  el.targetActivateBtn = document.getElementById("targetActivateBtn");
  el.targetDeleteBtn = document.getElementById("targetDeleteBtn");
  el.targetClearFormBtn = document.getElementById("targetClearFormBtn");
  el.targetHint = document.getElementById("targetHint");

  el.udDictName = document.getElementById("udDictName");
  el.autoSourceDict = document.getElementById("autoSourceDict");
  el.autoReloadDictsBtn = document.getElementById("autoReloadDictsBtn");
  el.autoRunBtn = document.getElementById("autoRunBtn");
  el.autoCancelRunBtn = document.getElementById("autoCancelRunBtn");
  el.autoIncludeCrud = document.getElementById("autoIncludeCrud");
  el.autoIncludeAllTypes = document.getElementById("autoIncludeAllTypes");
  el.autoVerboseSteps = document.getElementById("autoVerboseSteps");
  el.autoRefreshReportsBtn = document.getElementById("autoRefreshReportsBtn");
  el.autoDownloadReportBtn = document.getElementById("autoDownloadReportBtn");
  el.autoDeleteReportBtn = document.getElementById("autoDeleteReportBtn");
  el.autoRunsTable = document.getElementById("autoRunsTable");
  el.autoStepsTable = document.getElementById("autoStepsTable");
  el.autoRunStatus = document.getElementById("autoRunStatus");
  el.autoHumanSummary = document.getElementById("autoHumanSummary");
  el.autoDictSnapshotMeta = document.getElementById("autoDictSnapshotMeta");
  el.autoDictSnapshotTable = document.getElementById("autoDictSnapshotTable");
  el.autoReportJson = document.getElementById("autoReportJson");
  el.udCreateMode = document.getElementById("udCreateMode");
  el.udPresetWrap = document.getElementById("udPresetWrap");
  el.udManualWrap = document.getElementById("udManualWrap");
  el.udPreset = document.getElementById("udPreset");
  el.createAddColumnBtn = document.getElementById("createAddColumnBtn");
  el.createSyncSeedBtn = document.getElementById("createSyncSeedBtn");
  el.createSeedAddRowBtn = document.getElementById("createSeedAddRowBtn");
  el.createColumns = document.getElementById("createColumns");
  el.createSeedGrid = document.getElementById("createSeedGrid");
  el.udCreateBtn = document.getElementById("udCreateBtn");
  el.udRemoveBtn = document.getElementById("udRemoveBtn");
  el.udMetainfoBtn = document.getElementById("udMetainfoBtn");
  el.udQueryFrameBtn = document.getElementById("udQueryFrameBtn");
  el.udQueryBtn = document.getElementById("udQueryBtn");
  el.udSessionHint = document.getElementById("udSessionHint");

  el.insertColumns = document.getElementById("insertColumns");
  el.insertBuildGridBtn = document.getElementById("insertBuildGridBtn");
  el.insertAddRowBtn = document.getElementById("insertAddRowBtn");
  el.insertSendBtn = document.getElementById("insertSendBtn");
  el.insertGrid = document.getElementById("insertGrid");

  el.searchAddFilterBtn = document.getElementById("searchAddFilterBtn");
  el.searchBtn = document.getElementById("searchBtn");
  el.selectFieldsBtn = document.getElementById("selectFieldsBtn");
  el.searchFilters = document.getElementById("searchFilters");
  el.searchResults = document.getElementById("searchResults");
  el.searchSummary = document.getElementById("searchSummary");

  el.updateRowId = document.getElementById("updateRowId");
  el.updateAddFieldBtn = document.getElementById("updateAddFieldBtn");
  el.updateFields = document.getElementById("updateFields");
  el.updateSendBtn = document.getElementById("updateSendBtn");

  el.fileRowId = document.getElementById("fileRowId");
  el.fileColumn = document.getElementById("fileColumn");
  el.fileIndex = document.getElementById("fileIndex");
  el.fileUploadInput = document.getElementById("fileUploadInput");
  el.fileUploadResetBtn = document.getElementById("fileUploadResetBtn");
  el.fileUploadBtn = document.getElementById("fileUploadBtn");
  el.fileDownloadBtn = document.getElementById("fileDownloadBtn");
  el.fileClearBtn = document.getElementById("fileClearBtn");
  el.fileHint = document.getElementById("fileHint");

  el.deleteMode = document.getElementById("deleteMode");
  el.deleteAllowMany = document.getElementById("deleteAllowMany");
  el.deleteAddFilterBtn = document.getElementById("deleteAddFilterBtn");
  el.deleteSendBtn = document.getElementById("deleteSendBtn");
  el.deleteFilters = document.getElementById("deleteFilters");
  el.deleteRowId = document.getElementById("deleteRowId");
  el.deleteHint = document.getElementById("deleteHint");

  el.udLastResponse = document.getElementById("udLastResponse");
  el.udLastResponseDownloadBtn = document.getElementById("udLastResponseDownloadBtn");

  el.restDictName = document.getElementById("restDictName");
  el.restTableUid = document.getElementById("restTableUid");
  el.restListBtn = document.getElementById("restListBtn");
  el.restCreateBtn = document.getElementById("restCreateBtn");
  el.restMetaBtn = document.getElementById("restMetaBtn");
  el.restRowsBtn = document.getElementById("restRowsBtn");
  el.restDeleteBtn = document.getElementById("restDeleteBtn");
  el.restHint = document.getElementById("restHint");
  el.restInsertAddFieldBtn = document.getElementById("restInsertAddFieldBtn");
  el.restInsertBtn = document.getElementById("restInsertBtn");
  el.restInsertFields = document.getElementById("restInsertFields");
  el.restUpdateRowId = document.getElementById("restUpdateRowId");
  el.restUpdateAddFieldBtn = document.getElementById("restUpdateAddFieldBtn");
  el.restUpdateBtn = document.getElementById("restUpdateBtn");
  el.restUpdateFields = document.getElementById("restUpdateFields");
  el.restResponse = document.getElementById("restResponse");

  el.pgLimit = document.getElementById("pgLimit");
  el.pgOffset = document.getElementById("pgOffset");
  el.pgSearch = document.getElementById("pgSearch");
  el.pgFilesFilter = document.getElementById("pgFilesFilter");
  el.pgListBtn = document.getElementById("pgListBtn");
  el.pgResultsTable = document.getElementById("pgResultsTable");
  el.pgSelectedId = document.getElementById("pgSelectedId");
  el.pgLoadDetailBtn = document.getElementById("pgLoadDetailBtn");
  el.pgLoadContentBtn = document.getElementById("pgLoadContentBtn");
  el.pgExportJsonBtn = document.getElementById("pgExportJsonBtn");
  el.pgExportCsvBtn = document.getElementById("pgExportCsvBtn");
  el.pgExportXlsxBtn = document.getElementById("pgExportXlsxBtn");
  el.pgExportZipBtn = document.getElementById("pgExportZipBtn");
  el.pgResponse = document.getElementById("pgResponse");

  ensureFileUploadResetButton();
}

function ensureFileUploadResetButton() {
  if (el.fileUploadResetBtn || !el.fileUploadInput) {
    return;
  }
  const row = el.fileUploadInput.closest(".file-input-row");
  if (!row) {
    return;
  }
  const btn = document.createElement("button");
  btn.id = "fileUploadResetBtn";
  btn.type = "button";
  btn.className = "btn btn-ghost btn-small";
  btn.textContent = "Сбросить";
  row.appendChild(btn);
  el.fileUploadResetBtn = btn;
}

function setupNavigation() {
  el.menuButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const targetId = button.dataset.section;
      el.menuButtons.forEach((item) => item.classList.toggle("active", item === button));
      el.sections.forEach((section) => section.classList.toggle("active", section.id === targetId));
    });
  });
}

function setupConnectionBar() {
  el.quickParagraphLogin?.addEventListener("input", () => {
    if (el.targetIshdLogin) {
      el.targetIshdLogin.value = el.quickParagraphLogin.value;
    }
  });

  el.quickParagraphPassword?.addEventListener("input", () => {
    if (el.targetIshdPassword) {
      el.targetIshdPassword.value = el.quickParagraphPassword.value;
    }
  });

  el.targetIshdLogin?.addEventListener("input", () => {
    if (el.quickParagraphLogin) {
      el.quickParagraphLogin.value = el.targetIshdLogin.value;
    }
  });

  el.targetIshdPassword?.addEventListener("input", () => {
    if (el.quickParagraphPassword) {
      el.quickParagraphPassword.value = el.targetIshdPassword.value;
    }
  });

  bindActionButton(el.saveApiBase, async () => {
    const nextBase = normalizeApiBase(el.apiBase.value);
    if (!nextBase) {
      throw new Error("Укажите корректный backend URL.");
    }
    state.apiBase = nextBase;
    localStorage.setItem(API_BASE_KEY, nextBase);
    toast(`Backend URL saved: ${nextBase}`, "ok");
  }, { pendingText: "Выполняется..." });

  bindActionButton(el.pingApi, async () => {
    const currentBase = normalizeApiBase(el.apiBase?.value || state.apiBase || "");
    if (/^https?:\/\/[^/]+:50200$/i.test(currentBase)) {
      throw new Error("В поле backend указан порт ИШД (50200). Для backend используйте http://127.0.0.1:8000.");
    }

    const selected = state.targets.find((item) => Number(item?.id) === Number(state.targetId));
    const selectedName = selected?.name ? String(selected.name) : "target";
    const restoreHint = () => {
      if (!el.targetHint) {
        return;
      }
      const current = state.targets.find((item) => String(item?.id ?? "") === String(state.targetId ?? ""));
      const label = current ? current.name : "env-default";
      el.targetHint.textContent = `Текущая цель: ${label}`;
    };
    try {
      if (state.targetId != null) {
        if (state.ishdProbeAutoRunning) {
          toast("Автопроверка ISHD уже выполняется. Ожидайте статус внизу формы.", "ok");
          return;
        }
        if (el.targetHint) {
          el.targetHint.textContent = `Проверка "${selectedName}": ожидание готовности ISHD...`;
        }
        const { probe, attempts, waitedMs } = await probeTargetWithIshdWarmup(
          state.targetId,
          ({ attempt, elapsedMs }) => {
            if (!el.targetHint) {
              return;
            }
            const elapsedSec = Math.max(1, Math.ceil(Number(elapsedMs || 0) / 1000));
            el.targetHint.textContent = `Проверка "${selectedName}": попытка ${attempt}, прошло ${elapsedSec}s, ISHD пока недоступен...`;
          },
        );
        if (!probe || typeof probe !== "object") {
          throw new Error("Некорректный ответ проверки профиля.");
        }
        const parts = [
          `ISHD: ${probe?.ishd?.ok ? "ok" : "fail"}`,
          `REST: ${probe?.paragraph_rest?.ok ? "ok" : "fail"}`,
          `DB: ${probe?.paragraph_db?.ok ? "ok" : "fail"}`,
        ];
        const isIshdOk = !!probe?.ishd?.ok;
        const isRestOk = !!probe?.paragraph_rest?.ok;
        const isDbOk = !!probe?.paragraph_db?.ok;
        const restReason = String(probe?.paragraph_rest?.message || "").trim();
        const level = probe?.ok ? "ok" : (isIshdOk && isDbOk ? "ok" : "error");
        let message = `Profile check: ${parts.join(" | ")}`;
        if (isIshdOk && !isRestOk) {
          message += " | ISHD работает, REST API недоступен";
          if (restReason) {
            message += `: ${restReason}`;
          }
        }
        if (attempts > 1) {
          const waitedSec = Math.max(1, Math.ceil(Number(waitedMs || 0) / 1000));
          if (probe?.ishd?.ok) {
            message += ` | ISHD ready after ${waitedSec}s (${attempts} tries)`;
          } else {
            message += ` | ISHD wait timeout ${waitedSec}s (${attempts} tries)`;
          }
        }
        if (!isIshdOk) {
          message += " | Запущена авто-проверка ISHD (до 60s)";
        }
        toast(message, level);
        if (!isIshdOk) {
          startIshdAutoProbe(state.targetId, selectedName);
        }
      } else {
        throw new Error("Выберите профиль стенда и сделайте его активным перед проверкой логина/пароля.");
      }
    } catch (error) {
      toast(error.message, "error");
      throw error;
    } finally {
      if (!state.ishdProbeAutoRunning) {
        restoreHint();
      }
    }
  }, { pendingText: "Выполняется..." });

  bindActionButton(el.targetReloadBtn, async () => {
    await loadTargets({ rethrow: true });
  }, { pendingText: "Выполняется..." });

  bindActionButton(el.targetAutoCurrentBtn, handleTargetAutoCurrent, { pendingText: "Выполняется..." });
}

async function probeTargetWithIshdWarmup(targetId, onProgress) {
  const startedAt = Date.now();
  const attempts = 1;
  const probe = await apiRequest(`/targets/${encodeURIComponent(targetId)}/probe`, {
    method: "POST",
    skipTarget: true,
    timeoutMs: 8000,
  });
  if (!probe?.ishd?.ok && typeof onProgress === "function") {
    onProgress({
      attempt: attempts,
      elapsedMs: Date.now() - startedAt,
      probe,
    });
  }

  return {
    probe,
    attempts,
    waitedMs: Date.now() - startedAt,
  };
}

function setTargetHintStatus(text) {
  if (!el.targetHint) {
    return;
  }
  el.targetHint.textContent = String(text || "").trim();
}

function stopIshdAutoProbe() {
  state.ishdProbeAutoRunning = false;
  state.ishdProbeAutoToken = 0;
}

function startIshdAutoProbe(targetId, targetName) {
  if (state.ishdProbeAutoRunning) {
    return;
  }
  state.ishdProbeAutoRunning = true;
  const token = Date.now();
  state.ishdProbeAutoToken = token;

  void (async () => {
    const startedAt = Date.now();
    let attempt = 1;
    while (state.ishdProbeAutoRunning && state.ishdProbeAutoToken === token) {
      const elapsedMs = Date.now() - startedAt;
      const elapsedSec = Math.max(1, Math.ceil(elapsedMs / 1000));
      setTargetHintStatus(`Проверка "${targetName}": попытка ${attempt}, прошло ${elapsedSec}s, ISHD пока недоступен...`);

      if (elapsedMs >= PROFILE_PROBE_BG_WAIT_MS) {
        toast(`ISHD по профилю "${targetName}" не стал доступен за ${elapsedSec}s.`, "error");
        stopIshdAutoProbe();
        break;
      }

      await sleep(PROFILE_PROBE_BG_RETRY_MS);
      if (!state.ishdProbeAutoRunning || state.ishdProbeAutoToken !== token) {
        break;
      }

      let probe = null;
      try {
        probe = await apiRequest(`/targets/${encodeURIComponent(targetId)}/probe`, {
          method: "POST",
          skipTarget: true,
          timeoutMs: 8000,
        });
      } catch {
        probe = null;
      }

      if (probe?.ishd?.ok) {
        const readySec = Math.max(1, Math.ceil((Date.now() - startedAt) / 1000));
        setTargetHintStatus(`Текущая цель: ${targetName} | ISHD доступен`);
        toast(`ISHD доступен: "${targetName}" (через ${readySec}s, попыток ${attempt + 1})`, "ok");
        stopIshdAutoProbe();
        break;
      }

      attempt += 1;
    }

    if (!state.ishdProbeAutoRunning && state.ishdProbeAutoToken === 0) {
      const current = state.targets.find((item) => String(item?.id ?? "") === String(state.targetId ?? ""));
      const label = current ? current.name : "env-default";
      setTargetHintStatus(`Текущая цель: ${label}`);
    }
  })();
}

function setupTargets() {
  el.targetSelect?.addEventListener("change", () => {
    const raw = String(el.targetSelect.value || "").trim();
    state.targetId = raw ? Number(raw) : null;
    if (state.targetId == null) {
      localStorage.removeItem(TARGET_ID_KEY);
    } else {
      localStorage.setItem(TARGET_ID_KEY, String(state.targetId));
    }
    const selected = state.targets.find((item) => String(item?.id ?? "") === raw);
    const label = selected ? selected.name : "env-default";
    if (el.targetHint) {
      el.targetHint.textContent = `Текущая цель: ${label}`;
    }
  });

  bindActionButton(el.targetCreateBtn, handleTargetCreate, { pendingText: "Выполняется..." });
  bindActionButton(el.targetUpdateBtn, handleTargetUpdate, { pendingText: "Выполняется..." });
  bindActionButton(el.targetActivateBtn, handleTargetActivate, { pendingText: "Выполняется..." });
  bindActionButton(el.targetDeleteBtn, handleTargetDelete, { pendingText: "Выполняется..." });
  bindActionButton(el.targetClearFormBtn, async () => clearTargetForm(), { pendingText: "Выполняется..." });
}

function setupUserDicts() {
  addFilterRow(el.searchFilters);
  addFilterRow(el.deleteFilters);
  addKvRow(el.updateFields);
  addCreateColumnRow();
  syncCreateSeedGrid();

  bindActionButton(el.searchAddFilterBtn, async () => addFilterRow(el.searchFilters), {
    pendingText: "Добавляем...",
    successText: "Добавлено",
    doneFlashMs: 500,
  });
  bindActionButton(el.deleteAddFilterBtn, async () => addFilterRow(el.deleteFilters), {
    pendingText: "Добавляем...",
    successText: "Добавлено",
    doneFlashMs: 500,
  });
  bindActionButton(el.updateAddFieldBtn, async () => addKvRow(el.updateFields), {
    pendingText: "Добавляем...",
    successText: "Добавлено",
    doneFlashMs: 500,
  });
  el.udCreateMode?.addEventListener("change", updateCreateModeUi);
  bindActionButton(el.createAddColumnBtn, async () => {
    addCreateColumnRow();
    syncCreateSeedGrid();
  }, {
    pendingText: "Добавляем...",
    successText: "Добавлено",
    doneFlashMs: 500,
  });
  bindActionButton(el.createSyncSeedBtn, async () => syncCreateSeedGrid(), {
    pendingText: "Синхронизация...",
    successText: "Готово",
    doneFlashMs: 500,
  });
  bindActionButton(el.createSeedAddRowBtn, async () => {
    addCreateSeedRow();
  }, {
    pendingText: "Добавляем...",
    successText: "Добавлено",
    doneFlashMs: 500,
  });

  bindActionButton(el.insertBuildGridBtn, async () => {
    resetInsertGridByColumns();
  }, {
    pendingText: "Построение...",
    successText: "Готово",
    doneFlashMs: 500,
  });
  bindActionButton(el.insertAddRowBtn, async () => {
    if (!state.insertColumns.length) {
      resetInsertGridByColumns();
    }
    addInsertRow();
  }, {
    pendingText: "Добавляем...",
    successText: "Добавлено",
    doneFlashMs: 500,
  });

  bindActionButton(el.udCreateBtn, handleCreateDict, { pendingText: "Выполняется..." });
  bindActionButton(el.udRemoveBtn, handleRemoveDict, { pendingText: "Выполняется..." });
  bindActionButton(el.udMetainfoBtn, handleMetainfo, { pendingText: "Выполняется..." });
  bindActionButton(el.udQueryFrameBtn, handleQueryFrame, { pendingText: "Выполняется..." });
  bindActionButton(el.udQueryBtn, handleQuery, { pendingText: "Выполняется..." });
  bindActionButton(el.insertSendBtn, handleInsertRows, { pendingText: "Выполняется..." });
  bindActionButton(el.searchBtn, handleSearch, { pendingText: "Выполняется..." });
  bindActionButton(el.selectFieldsBtn, handleSelectFields, { pendingText: "Выполняется..." });
  bindActionButton(el.updateSendBtn, handleUpdateRow, { pendingText: "Выполняется..." });
  bindActionButton(el.fileUploadBtn, handleFileUpload, { pendingText: "Загрузка..." });
  bindActionButton(el.fileDownloadBtn, handleFileDownload, { pendingText: "Скачивание..." });
  bindActionButton(el.fileClearBtn, handleFileClear, {
    pendingText: "Очистка...",
    successText: "Очищено",
    doneFlashMs: 450,
  });
  bindActionButton(el.fileUploadResetBtn, handleFileClear, {
    pendingText: "Сброс...",
    successText: "Очищено",
    doneFlashMs: 350,
  });
  bindActionButton(el.udLastResponseDownloadBtn, handleUdLastResponseDownload, {
    pendingText: "Подготовка...",
    successText: "Скачано",
    doneFlashMs: 500,
  });
  bindActionButton(el.deleteSendBtn, handleDeleteRows, { pendingText: "Выполняется..." });

  bindActionButton(el.autoReloadDictsBtn, handleAutoLoadDicts, {
    pendingText: "Обновляем...",
    successText: "Готово",
    doneFlashMs: 600,
  });
  bindActionButton(el.autoRunBtn, handleAutoRun, {
    pendingText: "Запуск...",
    successText: "Запущено",
    doneFlashMs: 600,
  });
  bindActionButton(el.autoCancelRunBtn, handleAutoCancelRun, {
    pendingText: "Останавливаем...",
    successText: "Запрошено",
    doneFlashMs: 600,
  });
  bindActionButton(
    el.autoRefreshReportsBtn,
    async () => handleAutoLoadReports({ rethrow: true }),
    { pendingText: "Обновляем...", successText: "Готово", doneFlashMs: 600 },
  );
  bindActionButton(
    el.autoDownloadReportBtn,
    async () => handleAutoDownloadReport({ rethrow: true }),
    { pendingText: "Подготовка...", successText: "Скачано", doneFlashMs: 700 },
  );
  bindActionButton(
    el.autoDeleteReportBtn,
    async () => handleAutoDeleteReport({ rethrow: true }),
    { pendingText: "Удаляем...", successText: "Удалено", doneFlashMs: 800 },
  );
  setAutoRunUiStateIdle("Готово к запуску");
  updateAutoReportActionButtons();
  renderAutoDictSnapshot(null);

  el.autoSourceDict?.addEventListener("change", () => {
    const selected = String(el.autoSourceDict.value || "").trim();
    if (selected && el.udDictName) {
      el.udDictName.value = selected;
    }
  });

  el.udDictName?.addEventListener("input", () => {
    const typed = String(el.udDictName.value || "").trim();
    if (!el.autoSourceDict) {
      return;
    }
    if (!typed) {
      return;
    }
    const match = Array.from(el.autoSourceDict.options || []).find(
      (opt) => String(opt?.value || "").trim() === typed,
    );
    if (match) {
      el.autoSourceDict.value = typed;
    }
  });

  el.fileUploadInput?.addEventListener("click", () => {
    // Allow selecting the same file twice in a row by clearing previous value on open.
    el.fileUploadInput.value = "";
  });

  el.fileUploadInput?.addEventListener("change", () => {
    if (!el.fileHint) {
      return;
    }
    const file = el.fileUploadInput?.files?.[0] || null;
    if (!file) {
      el.fileHint.textContent = state.selectedRowId
        ? `Выбрана строка: ${state.selectedRowId}. Укажите колонку с файлом и запустите операцию.`
        : "Выберите строку в таблице Search/Select Fields или введите row_id вручную.";
      return;
    }
    el.fileHint.textContent = `Выбран файл: ${file.name}`;
  });
}

function updateCreateModeUi() {
  const isManual = (el.udCreateMode?.value || "preset") === "manual";
  el.udPresetWrap?.classList.toggle("hidden", isManual);
  el.udManualWrap?.classList.toggle("hidden", !isManual);
}

function getCreateTypeOptions() {
  const fromApi = state.createColumnTypes
    .map((item) => ({
      key: String(item?.key || "").trim(),
      label: String(item?.label || "").trim(),
    }))
    .filter((item) => item.key);
  if (fromApi.length) {
    return fromApi;
  }
  return [
    { key: "text", label: "text" },
    { key: "text_area", label: "text_area" },
    { key: "int", label: "int" },
    { key: "double", label: "double" },
    { key: "datetime", label: "datetime" },
    { key: "date", label: "date" },
    { key: "bool", label: "bool" },
    { key: "link", label: "link" },
  ];
}

function createTypeOptionsMarkup(selectedKey) {
  const options = getCreateTypeOptions();
  return options
    .map((item) => {
      const selected = item.key === selectedKey ? " selected" : "";
      return `<option value="${escapeHtml(item.key)}"${selected}>${escapeHtml(item.key)} (${escapeHtml(item.label)})</option>`;
    })
    .join("");
}

function addCreateColumnRow(initial = {}) {
  if (!el.createColumns) {
    return;
  }
  const row = document.createElement("div");
  row.className = "create-col-row";
  const selectedType = String(initial.type || "text").trim() || "text";
  row.innerHTML = `
    <input type="text" class="col-name" placeholder="название колонки" value="${escapeHtml(initial.name || "")}" />
    <select class="col-type">${createTypeOptionsMarkup(selectedType)}</select>
    <label class="checkbox-label"><input type="checkbox" class="col-required" ${initial.required === false ? "" : "checked"} />обязательно</label>
    <input type="text" class="col-ref-dict" placeholder="ref_dict (для link)" value="${escapeHtml(initial.ref_dict || "")}" />
    <input type="text" class="col-ref-column" placeholder="ref_column (для link)" value="${escapeHtml(initial.ref_column || "")}" />
    <label class="checkbox-label"><input type="checkbox" class="col-cascade" ${initial.cascade ? "checked" : ""} />каскадное удаление</label>
    <button class="icon-btn" type="button">×</button>
  `;
  row.querySelector(".icon-btn").addEventListener("click", () => {
    row.remove();
    if (!el.createColumns.children.length) {
      addCreateColumnRow();
    }
    syncCreateSeedGrid();
  });
  row.querySelector(".col-name").addEventListener("blur", () => syncCreateSeedGrid());
  el.createColumns.appendChild(row);
}

function rerenderCreateColumnTypeSelects() {
  Array.from(el.createColumns.querySelectorAll(".create-col-row")).forEach((row) => {
    const select = row.querySelector(".col-type");
    const selected = select.value || "text";
    select.innerHTML = createTypeOptionsMarkup(selected);
    if (!select.value) {
      select.value = "text";
    }
  });
}

function readCreateColumns() {
  return Array.from(el.createColumns.querySelectorAll(".create-col-row"))
    .map((row) => ({
      name: row.querySelector(".col-name").value.trim(),
      type: row.querySelector(".col-type").value.trim() || "text",
      required: row.querySelector(".col-required").checked,
      ref_dict: row.querySelector(".col-ref-dict").value.trim(),
      ref_column: row.querySelector(".col-ref-column").value.trim(),
      cascade: row.querySelector(".col-cascade").checked,
    }))
    .filter((col) => col.name);
}

function getCreateSeedColumns() {
  return readCreateColumns().map((col) => col.name);
}

function syncCreateSeedGrid() {
  const columns = getCreateSeedColumns();
  if (!el.createSeedGrid) {
    return;
  }
  if (!columns.length) {
    state.createSeedRows = [];
    renderCreateSeedGrid([]);
    return;
  }
  state.createSeedRows = state.createSeedRows.map((row) => {
    const normalized = {};
    columns.forEach((col) => {
      normalized[col] = row?.[col] ?? "";
    });
    return normalized;
  });
  if (!state.createSeedRows.length) {
    addCreateSeedRow(columns);
    return;
  }
  renderCreateSeedGrid(columns);
}

function addCreateSeedRow(columns = getCreateSeedColumns()) {
  if (!columns.length) {
    return;
  }
  const row = {};
  columns.forEach((col) => {
    row[col] = "";
  });
  state.createSeedRows.push(row);
  renderCreateSeedGrid(columns);
}

function renderCreateSeedGrid(columns = getCreateSeedColumns()) {
  const table = el.createSeedGrid;
  if (!table) {
    return;
  }
  table.innerHTML = "";
  if (!columns.length) {
    table.innerHTML = "<tbody><tr><td>Добавьте хотя бы одну колонку выше</td></tr></tbody>";
    return;
  }

  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  columns.forEach((col) => {
    const th = document.createElement("th");
    th.textContent = col;
    headRow.appendChild(th);
  });
  const removeTh = document.createElement("th");
  removeTh.textContent = "";
  headRow.appendChild(removeTh);
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  state.createSeedRows.forEach((row, rowIndex) => {
    const tr = document.createElement("tr");
    columns.forEach((col) => {
      const td = document.createElement("td");
      const input = document.createElement("input");
      input.type = "text";
      input.value = row?.[col] ?? "";
      input.addEventListener("input", (event) => {
        state.createSeedRows[rowIndex][col] = event.target.value;
      });
      td.appendChild(input);
      tr.appendChild(td);
    });
    const tdRemove = document.createElement("td");
    const btn = document.createElement("button");
    btn.className = "icon-btn";
    btn.type = "button";
    btn.textContent = "×";
    btn.addEventListener("click", () => {
      state.createSeedRows.splice(rowIndex, 1);
      if (!state.createSeedRows.length) {
        addCreateSeedRow(columns);
        return;
      }
      renderCreateSeedGrid(columns);
    });
    tdRemove.appendChild(btn);
    tr.appendChild(tdRemove);
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
}

function parseCreateSeedValue(raw, columnType) {
  const type = String(columnType || "").toLowerCase();
  const value = String(raw ?? "").trim();
  if (value === "") {
    return "";
  }
  if (type === "uuid") {
    if (!isValidUuidText(value)) {
      throw new Error("Неверный UUID.");
    }
    return value;
  }
  if (type === "bool") {
    if (/^(true|1|yes|да)$/i.test(value)) return true;
    if (/^(false|0|no|нет)$/i.test(value)) return false;
  }
  if (type === "int") {
    const parsed = Number.parseInt(value, 10);
    return Number.isNaN(parsed) ? value : parsed;
  }
  if (type === "double") {
    const parsed = Number.parseFloat(value);
    return Number.isNaN(parsed) ? value : parsed;
  }
  return value;
}

function collectCreateSeedRows() {
  const columns = readCreateColumns();
  const typeByName = Object.fromEntries(columns.map((col) => [col.name, col.type]));
  return state.createSeedRows
    .map((row, rowIndex) => {
      const out = {};
      Object.entries(row || {}).forEach(([key, raw]) => {
        const clean = String(raw ?? "").trim();
        if (clean === "") {
          return;
        }
        try {
          out[key] = parseCreateSeedValue(clean, typeByName[key]);
        } catch (error) {
          throw new Error(`Некорректное значение стартовой строки: ${error.message}`);
        }
      });
      return out;
    })
    .filter((row) => Object.keys(row).length > 0);
}

function isValidUuidText(value) {
  const normalized = String(value || "").trim().replace(/^\{|\}$/g, "");
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(normalized);
}

function setupDictsRest() {
  addKvRow(el.restInsertFields, { key: "name", value: "\u0418\u0432\u0430\u043d" });
  addKvRow(el.restUpdateFields, { key: "description", value: "updated" });

  bindActionButton(el.restInsertAddFieldBtn, async () => addKvRow(el.restInsertFields), {
    pendingText: "Добавляем...",
    successText: "Добавлено",
    doneFlashMs: 500,
  });
  bindActionButton(el.restUpdateAddFieldBtn, async () => addKvRow(el.restUpdateFields), {
    pendingText: "Добавляем...",
    successText: "Добавлено",
    doneFlashMs: 500,
  });

  bindActionButton(el.restListBtn, handleRestList, { pendingText: "Выполняется..." });
  bindActionButton(el.restCreateBtn, handleRestCreate, { pendingText: "Выполняется..." });
  bindActionButton(el.restMetaBtn, handleRestMeta, { pendingText: "Выполняется..." });
  bindActionButton(el.restRowsBtn, handleRestRows, { pendingText: "Выполняется..." });
  bindActionButton(el.restDeleteBtn, handleRestDelete, { pendingText: "Выполняется..." });
  bindActionButton(el.restInsertBtn, handleRestInsertRow, { pendingText: "Выполняется..." });
  bindActionButton(el.restUpdateBtn, handleRestUpdateRow, { pendingText: "Выполняется..." });
}

function setupParagraphSection() {
  bindActionButton(el.pgListBtn, handleParagraphList, { pendingText: "Выполняется..." });
  bindActionButton(el.pgLoadDetailBtn, handleParagraphDetail, { pendingText: "Выполняется..." });
  bindActionButton(el.pgLoadContentBtn, handleParagraphContent, { pendingText: "Выполняется..." });
  bindActionButton(el.pgExportJsonBtn, async () => openParagraphExport("json"), { pendingText: "Выполняется...", doneFlashMs: 500 });
  bindActionButton(el.pgExportCsvBtn, async () => openParagraphExport("csv"), { pendingText: "Выполняется...", doneFlashMs: 500 });
  bindActionButton(el.pgExportXlsxBtn, async () => openParagraphExport("excel"), { pendingText: "Выполняется...", doneFlashMs: 500 });
  bindActionButton(el.pgExportZipBtn, async () => openParagraphArchive(), { pendingText: "Выполняется...", doneFlashMs: 500 });
}

function bindActionButton(button, handler, options = {}) {
  if (!button || typeof handler !== "function") {
    return;
  }

  const idleLabel = String(button.textContent || "").trim() || "Запуск";
  button.dataset.idleLabel = idleLabel;

  button.addEventListener("click", async (event) => {
    event?.preventDefault?.();
    await runButtonAction(button, () => handler(event), options);
  });
}

async function runButtonAction(button, action, options = {}) {
  if (!button || typeof action !== "function") {
    return;
  }
  if (button.dataset.busy === "1") {
    return;
  }

  const idleLabel = button.dataset.idleLabel || String(button.textContent || "").trim() || "Запуск";
  const pendingLabel = options.pendingText || "Выполняется...";
  const successLabel = options.successText || "Выполнено";
  const errorLabel = options.errorText || "Ошибка";
  const doneFlashMs = Number.isFinite(options.doneFlashMs) ? Number(options.doneFlashMs) : 450;
  const errorFlashMs = Number.isFinite(options.errorFlashMs) ? Number(options.errorFlashMs) : 900;

  clearButtonStateTimer(button);
  button.dataset.busy = "1";
  button.disabled = true;
  setButtonState(button, "running", pendingLabel);
  const startedAt = performance.now();
  const actionName =
    String(options.perfName || button?.id || button?.dataset?.action || idleLabel || "button-action").trim();

  let failed = false;
  try {
    await action();
  } catch (error) {
    failed = true;
    console.error(error);
  } finally {
    button.dataset.busy = "0";
    button.disabled = false;
    recordUiActionPerf(actionName, performance.now() - startedAt, !failed);
  }

  flashButtonState(
    button,
    failed ? "error" : "ok",
    failed ? errorLabel : successLabel,
    failed ? errorFlashMs : doneFlashMs,
    idleLabel,
  );
}

function setButtonState(button, state, text) {
  if (!button) {
    return;
  }
  button.dataset.runState = state;
  if (typeof text === "string" && text) {
    button.textContent = repairMojibakeString(text);
  }
}

function clearButtonStateTimer(button) {
  const activeTimer = buttonStateTimers.get(button);
  if (activeTimer) {
    window.clearTimeout(activeTimer);
    buttonStateTimers.delete(button);
  }
}

function flashButtonState(button, state, text, timeoutMs, idleLabel) {
  if (!button) {
    return;
  }
  setButtonState(button, state, text);
  clearButtonStateTimer(button);

  const timer = window.setTimeout(() => {
    if (button.dataset.busy === "1") {
      return;
    }
    setButtonState(button, "idle", idleLabel || button.dataset.idleLabel || "Запуск");
    buttonStateTimers.delete(button);
  }, Math.max(250, Number(timeoutMs) || 900));

  buttonStateTimers.set(button, timer);
}

function hydrateApiBase() {
  const saved = localStorage.getItem(API_BASE_KEY);
  const currentOrigin = normalizeApiBase(window.location?.origin || "");
  const savedNormalized = normalizeApiBase(saved);
  const savedIsLoopback = /^(https?:\/\/)?(127\.0\.0\.1|localhost)(:\d+)?$/i.test(savedNormalized || "");
  const originIsRemote = !!currentOrigin && !/^(https?:\/\/)?(127\.0\.0\.1|localhost)(:\d+)?$/i.test(currentOrigin);
  if (savedNormalized && !(savedIsLoopback && originIsRemote)) {
    state.apiBase = savedNormalized;
  } else {
    state.apiBase = currentOrigin || DEFAULT_API_BASE;
  }
  el.apiBase.value = state.apiBase;

  const savedTarget = String(localStorage.getItem(TARGET_ID_KEY) || "").trim();
  if (savedTarget && /^-?\d+$/.test(savedTarget)) {
    state.targetId = Number(savedTarget);
  } else {
    state.targetId = null;
  }
}

async function bootstrapPage() {
  resetInsertGridByColumns();
  updateCreateModeUi();
  syncCreateSeedGrid();
  await loadTargets();
  await loadColumnTypesAndPresets();
  await handleAutoLoadDicts();
  await handleAutoLoadReports();
  await resumeAutoRunIfNeeded();
  await handleParagraphList();
}

async function resumeAutoRunIfNeeded() {
  try {
    const payload = await apiRequest("/dicts/autotest/jobs/current");
    const job = payload?.job;
    if (!job || !job.job_id) {
      return;
    }
    const status = String(job.status || "").toLowerCase();
    if (status !== "queued" && status !== "running") {
      return;
    }
    const dictName = String(job.source_dict_name || "dictionary");
    setAutoRunUiStateRunning(dictName);
    state.autoRunJobId = String(job.job_id);
    renderAutoProgress(job);
    if (state.autoRunPollTimerId != null) {
      window.clearInterval(state.autoRunPollTimerId);
    }
    state.autoRunPollTimerId = window.setInterval(() => {
      pollAutoRunJob(state.autoRunJobId);
    }, 1200);
  } catch {
    // silent on page bootstrap
  }
}

function toOptionalNumber(value, fallback) {
  const parsed = Number.parseInt(String(value ?? "").trim(), 10);
  return Number.isNaN(parsed) ? fallback : parsed;
}

function buildTargetPayloadFromForm() {
  const hostIdsRaw = String(el.targetHostIds?.value || "").trim() || "paragraf";
  const primaryHostId = hostIdsRaw
    .split(",")
    .map((item) => item.trim())
    .find((item) => item.length > 0) || "paragraf";
  const creds = readParagraphCredentials();

  return {
    name: String(el.targetName?.value || "").trim(),
    description: String(el.targetDescription?.value || "").trim() || null,
    ishd_host: String(el.targetIshdHost?.value || "").trim() || "127.0.0.1",
    ishd_port: toOptionalNumber(el.targetIshdPort?.value, 50200),
    ishd_host_id: String(el.targetIshdHostId?.value || "").trim() || "par_test_system",
    ishd_software_name: String(el.targetIshdSoftwareName?.value || "").trim() || "Paragraph Test System",
    ishd_login: creds.login,
    ishd_password: creds.password,
    ishd_target_host_id: primaryHostId,
    ishd_target_host_ids: hostIdsRaw,
    paragraph_rest_base_url: String(el.targetRestBase?.value || "").trim() || null,
    paragraph_db_dsn: String(el.targetParagraphDsn?.value || "").trim() || null,
  };
}

function readParagraphCredentials() {
  const quickLogin = String(el.quickParagraphLogin?.value || "").trim();
  const quickPassword = String(el.quickParagraphPassword?.value || "").trim();
  const advancedLogin = String(el.targetIshdLogin?.value || "").trim();
  const advancedPassword = String(el.targetIshdPassword?.value || "").trim();
  return {
    login: quickLogin || advancedLogin || null,
    password: quickPassword || advancedPassword || null,
  };
}

function setParagraphCredentials(login, password) {
  const nextLogin = String(login || "");
  const nextPassword = String(password || "");
  if (el.quickParagraphLogin) el.quickParagraphLogin.value = nextLogin;
  if (el.quickParagraphPassword) el.quickParagraphPassword.value = nextPassword;
  if (el.targetIshdLogin) el.targetIshdLogin.value = nextLogin;
  if (el.targetIshdPassword) el.targetIshdPassword.value = nextPassword;
}

function fillTargetForm(item) {
  if (!item) return;
  if (el.targetEditId) el.targetEditId.value = String(item.id ?? "");
  if (el.targetName) el.targetName.value = String(item.name || "");
  if (el.targetDescription) el.targetDescription.value = String(item.description || "");
  if (el.targetIshdHost) el.targetIshdHost.value = String(item.ishd?.host || "");
  if (el.targetIshdPort) el.targetIshdPort.value = String(item.ishd?.port || 50200);
  if (el.targetIshdHostId) el.targetIshdHostId.value = String(item.ishd?.host_id || "");
  if (el.targetIshdSoftwareName) {
    el.targetIshdSoftwareName.value = String(item.ishd?.software_name || "Paragraph Test System");
  }
  setParagraphCredentials(item.ishd?.login || "", item.ishd?.password || "");
  if (el.targetHostIds) el.targetHostIds.value = String(item.ishd?.target_host_ids || "paragraf");
  if (el.targetRestBase) el.targetRestBase.value = String(item.paragraph_rest_base_url || "");
  if (el.targetParagraphDsn) el.targetParagraphDsn.value = String(item.paragraph_db_dsn || "");
}

function clearTargetForm() {
  if (el.targetEditId) el.targetEditId.value = "";
  if (el.targetName) el.targetName.value = "";
  if (el.targetDescription) el.targetDescription.value = "";
  if (el.targetIshdHost) el.targetIshdHost.value = "127.0.0.1";
  if (el.targetIshdPort) el.targetIshdPort.value = "50200";
  if (el.targetIshdHostId) el.targetIshdHostId.value = "par_test_system";
  if (el.targetIshdSoftwareName) el.targetIshdSoftwareName.value = "Paragraph Test System";
  setParagraphCredentials("", "");
  if (el.targetHostIds) el.targetHostIds.value = "paragraf";
  if (el.targetRestBase) el.targetRestBase.value = "http://127.0.0.1:5000";
  if (el.targetParagraphDsn) el.targetParagraphDsn.value = "";
}

function renderTargets(items) {
  state.targets = Array.isArray(items) ? items : [];

  if (!el.targetSelect || !el.targetsTable) {
    return;
  }

  el.targetSelect.innerHTML = "";
  state.targets.forEach((item) => {
    const safeName = repairMojibakeString(String(item?.name || ""));
    const opt = document.createElement("option");
    opt.value = item.id == null ? "" : String(item.id);
    opt.textContent = item.id == null ? `${safeName} (fallback)` : `${safeName} [${item.id}]`;
    if (item.id == null) {
      opt.dataset.default = "1";
    }
    el.targetSelect.appendChild(opt);
  });

  if (state.targetId == null) {
    const active = state.targets.find((item) => item?.id != null && item?.is_active);
    if (active) {
      state.targetId = Number(active.id);
      localStorage.setItem(TARGET_ID_KEY, String(active.id));
    }
  }

  const wanted = state.targetId == null ? "" : String(state.targetId);
  if ([...el.targetSelect.options].some((o) => o.value === wanted)) {
    el.targetSelect.value = wanted;
  } else {
    el.targetSelect.value = "";
    state.targetId = null;
    localStorage.removeItem(TARGET_ID_KEY);
  }

  const rows = state.targets.map((item) => ({
    id: item.id == null ? "env-default" : item.id,
    name: item.name || "",
    description: item.description || "",
    is_active: item.is_active ? "yes" : "no",
    is_default: item.is_default ? "yes" : "no",
  }));
  renderDataTable(el.targetsTable, ["id", "name", "description", "is_active", "is_default"], rows, {
    clickable: true,
    onRowClick: async (row) => {
      const idRaw = String(row?.id || "");
      if (!idRaw || idRaw === "env-default") {
        clearTargetForm();
        el.targetSelect.value = "";
        state.targetId = null;
        localStorage.removeItem(TARGET_ID_KEY);
        return;
      }
      try {
        const payload = await apiRequest(`/targets/${encodeURIComponent(idRaw)}`);
        fillTargetForm(payload);
        el.targetSelect.value = String(payload.id);
        state.targetId = Number(payload.id);
        localStorage.setItem(TARGET_ID_KEY, String(payload.id));
      } catch (error) {
        toast(error.message, "error");
      }
    },
  });
}

async function loadTargets(options = {}) {
  const rethrow = Boolean(options?.rethrow);
  try {
    const payload = await apiRequest("/targets");
    const items = Array.isArray(payload?.items) ? payload.items : [];
    renderTargets(items);
    const selected = state.targets.find((item) => String(item?.id ?? "") === String(state.targetId ?? ""));
    if (el.targetHint) {
      el.targetHint.textContent = `Текущая цель: ${selected ? selected.name : "env-default"}`;
    }
  } catch (error) {
    toast(`Не удалось загрузить target'ы: ${error.message}`, "error");
    if (rethrow) {
      throw error;
    }
  }
}

async function handleTargetCreate() {
  try {
    const body = buildTargetPayloadFromForm();
    if (!body.name) {
      throw new Error("Введите имя профиля.");
    }
    await apiRequest("/targets", { method: "POST", body });
    toast("Профиль создан", "ok");
    await loadTargets({ rethrow: true });
  } catch (error) {
    toast(error.message, "error");
    throw error;
  }
}

async function handleTargetUpdate() {
  try {
    const id = String(el.targetEditId.value || "").trim();
    if (!id) {
      throw new Error("Выберите профиль для обновления.");
    }
    const body = buildTargetPayloadFromForm();
    await apiRequest(`/targets/${encodeURIComponent(id)}`, { method: "PATCH", body });
    toast("Профиль обновлен", "ok");
    await loadTargets({ rethrow: true });
  } catch (error) {
    toast(error.message, "error");
    throw error;
  }
}

async function handleTargetActivate() {
  try {
    const id = String(el.targetEditId.value || "").trim();
    if (!id) {
      throw new Error("Выберите профиль для активации.");
    }
    await apiRequest(`/targets/${encodeURIComponent(id)}/activate`, { method: "POST" });
    state.targetId = Number(id);
    localStorage.setItem(TARGET_ID_KEY, String(id));
    await loadTargets({ rethrow: true });
    toast("Профиль активирован", "ok");
  } catch (error) {
    toast(error.message, "error");
    throw error;
  }
}

async function handleTargetDelete() {
  try {
    const id = String(el.targetEditId.value || "").trim();
    if (!id) {
      throw new Error("Выберите профиль для удаления.");
    }
    await apiRequest(`/targets/${encodeURIComponent(id)}`, { method: "DELETE" });
    if (state.targetId != null && String(state.targetId) === id) {
      state.targetId = null;
      localStorage.removeItem(TARGET_ID_KEY);
    }
    clearTargetForm();
    await loadTargets({ rethrow: true });
    toast("Профиль удален", "ok");
  } catch (error) {
    toast(error.message, "error");
    throw error;
  }
}

async function handleTargetAutoCurrent() {
  try {
    const creds = readParagraphCredentials();

    const payload = {
      activate: true,
      paragraph_rest_port: 5000,
      ishd_login: creds.login || undefined,
      ishd_password: creds.password || undefined,
    };
    const response = await apiRequest("/targets/auto/current", {
      method: "POST",
      body: payload,
      skipTarget: true,
    });

    const created = response?.target;
    if (!created?.id) {
      throw new Error("Автосоздание профиля не вернуло id.");
    }

    state.targetId = Number(created.id);
    localStorage.setItem(TARGET_ID_KEY, String(created.id));
    await loadTargets({ rethrow: true });

    fillTargetForm(created);
    if (el.targetSelect) {
      el.targetSelect.value = String(created.id);
    }
    if (el.targetHint) {
      el.targetHint.textContent = `\u0422\u0435\u043a\u0443\u0449\u0430\u044f \u0446\u0435\u043b\u044c: ${created.name}`;
    }

    const effectiveIp = String(response?.effective_target_ip || created?.ishd?.host || "").trim();
    const restBaseUrl = String(response?.paragraph_rest_base_url || created?.paragraph_rest_base_url || "").trim();
    if (response?.is_local_profile) {
      toast(
        restBaseUrl
          ? `\u0410\u0432\u0442\u043e\u043d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0430 \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u0430: \u043b\u043e\u043a\u0430\u043b\u044c\u043d\u044b\u0439 \u0445\u043e\u0441\u0442, REST ${restBaseUrl}`
          : "\u0410\u0432\u0442\u043e\u043d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0430 \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u0430: \u043b\u043e\u043a\u0430\u043b\u044c\u043d\u044b\u0439 \u0445\u043e\u0441\u0442",
        "ok",
      );
    } else {
      toast(
        restBaseUrl
          ? `\u0410\u0432\u0442\u043e\u043d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0430 \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u0430: \u0441\u0442\u0435\u043d\u0434 ${effectiveIp}, REST ${restBaseUrl}`
          : `\u0410\u0432\u0442\u043e\u043d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0430 \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u0430: \u0441\u0442\u0435\u043d\u0434 ${effectiveIp}`,
        "ok",
      );
    }
  } catch (error) {
    toast(error.message, "error");
    throw error;
  }
}

async function loadColumnTypesAndPresets() {
  try {
    const data = await apiRequest("/dicts/column-types");
    state.createColumnTypes = Array.isArray(data?.types) ? data.types : [];
    const presets = Array.isArray(data?.presets) ? data.presets : [];
    el.udPreset.innerHTML = "";

    const emptyOption = document.createElement("option");
    emptyOption.value = "";
    emptyOption.textContent = "(без пресета, используется default backend)";
    el.udPreset.appendChild(emptyOption);

    presets.forEach((preset) => {
      const option = document.createElement("option");
      option.value = preset.key;
      option.textContent = `${preset.key} — ${preset.title}`;
      el.udPreset.appendChild(option);
    });

    const help = await apiRequest("/dicts/help");
    const workflow = Array.isArray(help?.workflow) ? help.workflow.join("  |  ") : "Памятка не получена";
    el.udSessionHint.textContent = workflow;
    rerenderCreateColumnTypeSelects();
    updateCreateModeUi();
    syncCreateSeedGrid();
  } catch (error) {
    toast(`Не удалось загрузить /dicts/help: ${error.message}`, "error");
  }
}

async function handleAutoLoadDicts() {
  if (state.autoDictsLoadInFlight) {
    return;
  }
  const startedAt = Date.now();
  state.autoDictsLoadInFlight = true;
  setAutoReloadDictsLoading(true);
  if (el.autoRunStatus && !state.autoRunInFlight) {
    el.autoRunStatus.dataset.state = "running";
    el.autoRunStatus.textContent = "Обновляем список справочников...";
  }

  try {
    const response = await apiRequest("/dicts/autotest/dicts");
    const items = Array.isArray(response?.items) ? response.items : [];
    const source = String(response?.source || "unknown");
    const targetName = String(response?.target_name || "").trim();
    el.autoSourceDict.innerHTML = "";

    if (!items.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "(список пуст)";
      el.autoSourceDict.appendChild(option);
      if (el.autoRunStatus && !state.autoRunInFlight) {
        el.autoRunStatus.dataset.state = "idle";
        el.autoRunStatus.textContent = "Список обновлён: 0 справочников";
      }
      toast("Список справочников пуст", "error");
      renderAutoDictSnapshot(null);
      return;
    }

    items.forEach((item) => {
      const name = repairMojibakeString(String(item?.name || "").trim());
      if (!name) {
        return;
      }
      const uid = String(item?.uid || "").trim();
      const option = document.createElement("option");
      option.value = name;
      option.textContent = uid ? `${name} (${uid})` : name;
      el.autoSourceDict.appendChild(option);
    });

    if (el.udDictName.value && items.some((item) => item?.name === el.udDictName.value)) {
      el.autoSourceDict.value = el.udDictName.value;
    }
    if (!el.autoSourceDict.value && items.length) {
      el.autoSourceDict.value = String(items[0]?.name || "");
    }
    if (el.autoSourceDict.value) {
      el.udDictName.value = el.autoSourceDict.value;
    }

    const elapsedSec = Math.max(0, (Date.now() - startedAt) / 1000);
    if (el.autoRunStatus && !state.autoRunInFlight) {
      el.autoRunStatus.dataset.state = "ok";
      el.autoRunStatus.textContent = `Список обновлён: ${items.length} | источник: ${source} | ${elapsedSec.toFixed(1)} c`;
    }
    const targetPart = targetName ? ` | цель: ${targetName}` : "";
    toast(`Справочники загружены: ${items.length}${targetPart}`, "ok");
  } catch (error) {
    if (el.autoSourceDict) {
      el.autoSourceDict.innerHTML = "";
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "(список не загружен)";
      el.autoSourceDict.appendChild(option);
    }
    if (el.autoRunStatus && !state.autoRunInFlight) {
      el.autoRunStatus.dataset.state = "error";
      el.autoRunStatus.textContent = `Не удалось обновить список: ${error.message}`;
    }
    toast(`Не удалось загрузить список справочников: ${error.message}`, "error");
    renderAutoDictSnapshot(null);
  } finally {
    state.autoDictsLoadInFlight = false;
    setAutoReloadDictsLoading(false);
  }
}

async function handleAutoLoadReports(options = {}) {
  const rethrow = Boolean(options?.rethrow);
  try {
    const response = await apiRequest("/dicts/autotest/reports", {
      query: { limit: 30 },
    });
    const items = Array.isArray(response?.items) ? response.items : [];
    state.autoReports = items;
    renderAutoRuns(items);
    updateAutoReportActionButtons();
  } catch (error) {
    toast(`Не удалось загрузить историю автотестов: ${error.message}`, "error");
    if (rethrow) {
      throw error;
    }
  }
}

function updateAutoReportActionButtons() {
  const hasSelection = Boolean(String(state.autoSelectedRunId || "").trim());
  if (el.autoDownloadReportBtn && el.autoDownloadReportBtn.dataset.busy !== "1") {
    el.autoDownloadReportBtn.disabled = !hasSelection;
  }
  if (el.autoDeleteReportBtn && el.autoDeleteReportBtn.dataset.busy !== "1") {
    el.autoDeleteReportBtn.disabled = !hasSelection;
  }
}

function buildAutoReportDownloadUrl(runId) {
  const rid = encodeURIComponent(String(runId || "").trim());
  const query = buildQuery({ target_id: state.targetId });
  return `${state.apiBase}/dicts/autotest/reports/${rid}/download${query}`;
}

async function handleAutoDownloadReport(options = {}) {
  const rethrow = Boolean(options?.rethrow);
  const runId = String(state.autoSelectedRunId || "").trim();
  if (!runId) {
    const err = new Error("Сначала выберите прогон в таблице истории.");
    if (rethrow) throw err;
    toast(err.message, "error");
    return;
  }
  try {
    const url = buildAutoReportDownloadUrl(runId);
    window.open(url, "_blank", "noopener,noreferrer");
    toast(`Запрошено скачивание полного JSON: ${runId}`, "ok");
  } catch (error) {
    toast(`Не удалось скачать отчет: ${error.message}`, "error");
    if (rethrow) {
      throw error;
    }
  }
}

async function handleAutoDeleteReport(options = {}) {
  const rethrow = Boolean(options?.rethrow);
  const runId = String(state.autoSelectedRunId || "").trim();
  if (!runId) {
    const err = new Error("Сначала выберите прогон в таблице истории.");
    if (rethrow) throw err;
    toast(err.message, "error");
    return;
  }
  const ok = window.confirm(`Удалить прогон ${runId} из истории?`);
  if (!ok) {
    return;
  }
  try {
    await apiRequest(`/dicts/autotest/reports/${encodeURIComponent(runId)}`, {
      method: "DELETE",
    });
    if (state.autoCurrentReport?.run_id === runId) {
      state.autoCurrentReport = null;
      state.autoLastOpenedRunId = null;
      setJson(el.autoReportJson, {});
      renderAutoHumanSummary(null);
      renderAutoSteps([]);
      renderAutoDictSnapshot(null);
    }
    state.autoSelectedRunId = "";
    updateAutoReportActionButtons();
    await handleAutoLoadReports({ rethrow: true });
    toast(`Прогон удален: ${runId}`, "ok");
  } catch (error) {
    toast(`Не удалось удалить прогон: ${error.message}`, "error");
    if (rethrow) {
      throw error;
    }
  }
}

function renderAutoRuns(items) {
  const formatDate = (raw) => {
    const text = String(raw || "").trim();
    if (!text) return "-";
    const d = new Date(text);
    if (Number.isNaN(d.getTime())) return text;
    return d.toLocaleString("ru-RU");
  };
  const formatDuration = (startedAt, finishedAt) => {
    const a = new Date(String(startedAt || ""));
    const b = new Date(String(finishedAt || ""));
    if (Number.isNaN(a.getTime()) || Number.isNaN(b.getTime())) {
      return "-";
    }
    const sec = Math.max(0, Math.round((b.getTime() - a.getTime()) / 1000));
    const mm = Math.floor(sec / 60);
    const ss = sec % 60;
    return `${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
  };
  const describeChecked = (item) => {
    const summary = item?.summary && typeof item.summary === "object" ? item.summary : {};
    const pre = summary?.preinstalled && typeof summary.preinstalled === "object" ? summary.preinstalled : {};
    const tmp = summary?.temporary && typeof summary.temporary === "object" ? summary.temporary : {};
    const parts = [];
    if (Number(pre.total || 0) > 0) {
      parts.push(`предустановленный (${Number(pre.total || 0)} шагов)`);
    }
    if (Number(tmp.total || 0) > 0) {
      parts.push(`временный CRUD (${Number(tmp.total || 0)} шагов)`);
    }
    return parts.length ? parts.join(" + ") : "базовая проверка";
  };
  const statusLabel = (raw) => {
    const v = String(raw || "").toLowerCase();
    if (v === "passed") return "Успешно";
    if (v === "failed") return "Ошибка";
    if (v === "cancelled") return "Остановлен";
    if (v === "running") return "Выполняется";
    if (v === "skipped") return "Пропущено";
    return v || "-";
  };

  const rows = (Array.isArray(items) ? items : []).map((item) => {
    const summary = item?.summary || {};
    const runId = String(item?.run_id || "");
    return {
      _run_id: runId,
      "ID прогона": runId,
      "Дата теста": formatDate(item?.started_at),
      "Длительность": formatDuration(item?.started_at, item?.finished_at),
      "Статус": statusLabel(item?.status),
      "Справочник": item?.source_dict_name || "",
      "Прошло": summary?.passed ?? 0,
      "Провалено": summary?.failed ?? 0,
      "Пропущено": summary?.skipped ?? 0,
      "Что проверяли": describeChecked(item),
    };
  });

  state.autoSelectedRunId = String(state.autoSelectedRunId || "").trim();
  if (state.autoSelectedRunId && !rows.some((row) => row._run_id === state.autoSelectedRunId)) {
    state.autoSelectedRunId = "";
  }
  updateAutoReportActionButtons();

  renderDataTable(
    el.autoRunsTable,
    [
      "ID прогона",
      "Дата теста",
      "Длительность",
      "Статус",
      "Справочник",
      "Прошло",
      "Провалено",
      "Пропущено",
      "Что проверяли",
    ],
    rows,
    {
      clickable: true,
      onRowClick: (row, tr) => {
        const runId = String(row?._run_id || "");
        if (!runId) {
          return;
        }
        state.autoSelectedRunId = runId;
        if (el.autoRunsTable) {
          markSelectedResultRow(el.autoRunsTable, tr);
        }
        updateAutoReportActionButtons();
        handleAutoOpenReport(runId);
      },
    },
  );

  if (state.autoSelectedRunId && el.autoRunsTable) {
    const rowIndex = rows.findIndex((row) => row._run_id === state.autoSelectedRunId);
    if (rowIndex >= 0) {
      const tr = el.autoRunsTable.querySelectorAll("tbody tr")[rowIndex];
      if (tr) {
        markSelectedResultRow(el.autoRunsTable, tr);
      }
    }
  }
}

function formatElapsed(seconds) {
  const safe = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  const mm = Math.floor(safe / 60);
  const ss = safe % 60;
  return `${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
}

function stopAutoRunTimer() {
  if (state.autoRunTimerId != null) {
    window.clearInterval(state.autoRunTimerId);
    state.autoRunTimerId = null;
  }
}

function stopAutoRunPolling() {
  if (state.autoRunPollTimerId != null) {
    window.clearInterval(state.autoRunPollTimerId);
    state.autoRunPollTimerId = null;
  }
  state.autoRunPollInFlight = false;
}

function setAutoReloadDictsLoading(isLoading) {
  if (!el.autoReloadDictsBtn) {
    return;
  }
  if (!el.autoReloadDictsBtn.dataset.defaultText) {
    el.autoReloadDictsBtn.dataset.defaultText = el.autoReloadDictsBtn.textContent || "Обновить список";
  }
  const defaultText = el.autoReloadDictsBtn.dataset.defaultText || "Обновить список";
  const loading = Boolean(isLoading);
  el.autoReloadDictsBtn.textContent = loading ? "Обновляем..." : defaultText;
  el.autoReloadDictsBtn.disabled = loading || Boolean(state.autoRunInFlight);
}

function setAutoRunUiStateRunning(dictName) {
  state.autoRunInFlight = true;
  state.autoRunStartedAtMs = Date.now();
  renderAutoDictSnapshot(null);
  if (el.autoRunBtn) {
    el.autoRunBtn.disabled = true;
    el.autoRunBtn.textContent = "Запустить автотест";
  }
  if (el.autoCancelRunBtn) {
    el.autoCancelRunBtn.disabled = false;
  }
  if (el.autoReloadDictsBtn) {
    setAutoReloadDictsLoading(state.autoDictsLoadInFlight);
  }
  if (el.autoRefreshReportsBtn) {
    el.autoRefreshReportsBtn.disabled = true;
  }

  const updateText = () => {
    if (!el.autoRunStatus) return;
    const elapsedSec = (Date.now() - (state.autoRunStartedAtMs || Date.now())) / 1000;
    el.autoRunStatus.dataset.state = "running";
    el.autoRunStatus.textContent = `Автотест "${dictName}" выполняется: ${formatElapsed(elapsedSec)}`;
  };

  updateText();
  stopAutoRunTimer();
  state.autoRunTimerId = window.setInterval(updateText, 1000);
}

function setAutoRunUiStateIdle(message, stateType = "idle") {
  stopAutoRunTimer();
  stopAutoRunPolling();
  state.autoRunInFlight = false;
  state.autoRunStartedAtMs = null;
  state.autoRunJobId = "";
  if (el.autoRunBtn) {
    el.autoRunBtn.disabled = false;
    el.autoRunBtn.textContent = "Запустить автотест";
  }
  if (el.autoCancelRunBtn) {
    el.autoCancelRunBtn.disabled = true;
  }
  if (el.autoReloadDictsBtn) {
    setAutoReloadDictsLoading(state.autoDictsLoadInFlight);
  }
  if (el.autoRefreshReportsBtn) {
    el.autoRefreshReportsBtn.disabled = false;
  }
  if (el.autoRunStatus) {
    el.autoRunStatus.dataset.state = stateType;
    el.autoRunStatus.textContent = message || "Готово";
  }
}

const AUTO_STATUS_LABELS = {
  passed: "\u0423\u0441\u043f\u0435\u0448\u043d\u043e",
  failed: "\u041e\u0448\u0438\u0431\u043a\u0430",
  cancelled: "\u041e\u0441\u0442\u0430\u043d\u043e\u0432\u043b\u0435\u043d",
  skipped: "\u041f\u0440\u043e\u043f\u0443\u0449\u0435\u043d\u043e",
  running: "\u0412\u044b\u043f\u043e\u043b\u043d\u044f\u0435\u0442\u0441\u044f",
};

const AUTO_STEP_NAME_BY_CODE = {
  "source.query_frame": "\u0421\u0442\u0440\u0443\u043a\u0442\u0443\u0440\u0430",
  "source.metainfo": "\u041c\u0435\u0442\u0430\u0438\u043d\u0444\u043e\u0440\u043c\u0430\u0446\u0438\u044f",
  "source.query": "\u041f\u043e\u043b\u043d\u044b\u0439 \u0437\u0430\u043f\u0440\u043e\u0441",
  "source.select_fields": "\u0412\u044b\u0431\u043e\u0440 \u043f\u043e\u043b\u0435\u0439",
  "source.search": "\u041f\u043e\u0438\u0441\u043a",
  "source.file.upload": "\u0417\u0430\u0433\u0440\u0443\u0437\u043a\u0430 \u0444\u0430\u0439\u043b\u0430",
  "source.file.download": "\u0421\u043a\u0430\u0447\u0438\u0432\u0430\u043d\u0438\u0435 \u0444\u0430\u0439\u043b\u0430",
  "temp.types.create": "\u0421\u043e\u0437\u0434\u0430\u043d\u0438\u0435 \u0442\u0435\u0441\u0442\u043e\u0432\u043e\u0433\u043e \u043e\u0431\u044a\u0435\u043a\u0442\u0430",
  "temp.types.remove": "\u0423\u0434\u0430\u043b\u0435\u043d\u0438\u0435 \u0442\u0435\u0441\u0442\u043e\u0432\u043e\u0433\u043e \u043e\u0431\u044a\u0435\u043a\u0442\u0430",
  "temp.crud.create": "\u0421\u043e\u0437\u0434\u0430\u043d\u0438\u0435 \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c\u0441\u043a\u043e\u0433\u043e \u0441\u043f\u0440\u0430\u0432\u043e\u0447\u043d\u0438\u043a\u0430",
  "temp.crud.insert": "\u0417\u0430\u043f\u0438\u0441\u044c \u0434\u0430\u043d\u043d\u044b\u0445",
  "temp.crud.search": "\u041f\u043e\u0438\u0441\u043a \u0434\u0430\u043d\u043d\u044b\u0445",
  "temp.crud.update": "\u0418\u0437\u043c\u0435\u043d\u0435\u043d\u0438\u0435 \u0434\u0430\u043d\u043d\u044b\u0445",
  "temp.crud.remove_rows": "\u0423\u0434\u0430\u043b\u0435\u043d\u0438\u0435 \u0441\u0442\u0440\u043e\u043a",
  "temp.crud.verify_removed": "\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0443\u0434\u0430\u043b\u0435\u043d\u0438\u044f",
  "temp.crud.remove_dict": "\u0423\u0434\u0430\u043b\u0435\u043d\u0438\u0435 \u0441\u043f\u0440\u0430\u0432\u043e\u0447\u043d\u0438\u043a\u0430",
};

const AUTO_XML_BY_CODE = {
  "source.query_frame": { file: "query_user_dict_frame.xml", description: "\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0432\u043e\u0437\u043c\u043e\u0436\u043d\u043e\u0441\u0442\u0438 \u0437\u0430\u043f\u0440\u043e\u0441\u0430 \u0441\u0442\u0440\u0443\u043a\u0442\u0443\u0440\u044b \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c\u0441\u043a\u0438\u0445 \u0441\u043f\u0440\u0430\u0432\u043e\u0447\u043d\u0438\u043a\u043e\u0432" },
  "source.metainfo": { file: "query_user_dict_metainfo.xml", description: "\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0432\u043e\u0437\u043c\u043e\u0436\u043d\u043e\u0441\u0442\u0438 \u0437\u0430\u043f\u0440\u043e\u0441\u0430 \u043c\u0435\u0442\u0430\u0438\u043d\u0444\u043e\u0440\u043c\u0430\u0446\u0438\u0438 \u043e \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c\u0441\u043a\u043e\u043c \u0441\u043f\u0440\u0430\u0432\u043e\u0447\u043d\u0438\u043a\u0435" },
  "source.query": { file: "query_user_dict.xml", description: "\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0432\u043e\u0437\u043c\u043e\u0436\u043d\u043e\u0441\u0442\u0438 \u0437\u0430\u043f\u0440\u043e\u0441\u0430 \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c\u0441\u043a\u0438\u0445 \u0441\u043f\u0440\u0430\u0432\u043e\u0447\u043d\u0438\u043a\u043e\u0432 (\u0432\u044b\u0432\u043e\u0434 \u0434\u0430\u043d\u043d\u044b\u0445 \u0441\u043f\u0440\u0430\u0432\u043e\u0447\u043d\u0438\u043a\u0430)" },
  "source.select_fields": { file: "select_fields_user_dict_v1.xml", description: "\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0432\u043e\u0437\u043c\u043e\u0436\u043d\u043e\u0441\u0442\u0438 \u0437\u0430\u043f\u0440\u043e\u0441\u0430 \u043f\u043e\u043b\u0435\u0439 \u0438\u0437 \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c\u0441\u043a\u043e\u0433\u043e \u0441\u043f\u0440\u0430\u0432\u043e\u0447\u043d\u0438\u043a\u0430" },
  "source.search": { file: "query_single_user_dict.xml", description: "\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0432\u043e\u0437\u043c\u043e\u0436\u043d\u043e\u0441\u0442\u0438 \u043f\u043e\u0438\u0441\u043a\u0430 \u0434\u0430\u043d\u043d\u044b\u0445 \u0432 \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c\u0441\u043a\u043e\u043c \u0441\u043f\u0440\u0430\u0432\u043e\u0447\u043d\u0438\u043a\u0435" },
  "source.file.upload": { file: "update_user_dict.xml", description: "\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0437\u0430\u0433\u0440\u0443\u0437\u043a\u0438 \u0444\u0430\u0439\u043b\u0430 \u0432 \u043f\u043e\u043b\u0435 \u0441\u043f\u0440\u0430\u0432\u043e\u0447\u043d\u0438\u043a\u0430" },
  "source.file.download": { file: "query_single_user_dict.xml", description: "\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0441\u043a\u0430\u0447\u0438\u0432\u0430\u043d\u0438\u044f \u0444\u0430\u0439\u043b\u0430 \u0438\u0437 \u043f\u043e\u043b\u044f \u0441\u043f\u0440\u0430\u0432\u043e\u0447\u043d\u0438\u043a\u0430" },
  "temp.crud.create": { file: "create_user_dict_v1.xml", description: "\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0432\u043e\u0437\u043c\u043e\u0436\u043d\u043e\u0441\u0442\u0438 \u0441\u043e\u0437\u0434\u0430\u043d\u0438\u044f \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c\u0441\u043a\u043e\u0433\u043e \u0441\u043f\u0440\u0430\u0432\u043e\u0447\u043d\u0438\u043a\u0430" },
  "temp.types.create": { file: "create_user_dict_v1.xml", description: "\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0432\u043e\u0437\u043c\u043e\u0436\u043d\u043e\u0441\u0442\u0438 \u0441\u043e\u0437\u0434\u0430\u043d\u0438\u044f \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c\u0441\u043a\u043e\u0433\u043e \u0441\u043f\u0440\u0430\u0432\u043e\u0447\u043d\u0438\u043a\u0430" },
  "temp.crud.remove_dict": { file: "remove_user_dict.xml", description: "\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0432\u043e\u0437\u043c\u043e\u0436\u043d\u043e\u0441\u0442\u0438 \u0443\u0434\u0430\u043b\u0435\u043d\u0438\u044f \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c\u0441\u043a\u043e\u0433\u043e \u0441\u043f\u0440\u0430\u0432\u043e\u0447\u043d\u0438\u043a\u0430" },
  "temp.types.remove": { file: "remove_user_dict.xml", description: "\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0432\u043e\u0437\u043c\u043e\u0436\u043d\u043e\u0441\u0442\u0438 \u0443\u0434\u0430\u043b\u0435\u043d\u0438\u044f \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c\u0441\u043a\u043e\u0433\u043e \u0441\u043f\u0440\u0430\u0432\u043e\u0447\u043d\u0438\u043a\u0430" },
  "temp.crud.insert": { file: "insert_user_dict.xml", description: "\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0432\u043e\u0437\u043c\u043e\u0436\u043d\u043e\u0441\u0442\u0438 \u0437\u0430\u043f\u0438\u0441\u0438 \u0432 \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c\u0441\u043a\u0438\u0439 \u0441\u043f\u0440\u0430\u0432\u043e\u0447\u043d\u0438\u043a" },
  "temp.crud.search": { file: "query_single_user_dict.xml", description: "\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0432\u043e\u0437\u043c\u043e\u0436\u043d\u043e\u0441\u0442\u0438 \u043f\u043e\u0438\u0441\u043a\u0430 \u0434\u0430\u043d\u043d\u044b\u0445 \u0432 \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c\u0441\u043a\u043e\u043c \u0441\u043f\u0440\u0430\u0432\u043e\u0447\u043d\u0438\u043a\u0435" },
  "temp.crud.verify_removed": { file: "query_single_user_dict.xml", description: "\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0444\u0430\u043a\u0442\u0430 \u0443\u0434\u0430\u043b\u0435\u043d\u0438\u044f \u0441\u0442\u0440\u043e\u043a\u0438 \u0438\u0437 \u0441\u043f\u0440\u0430\u0432\u043e\u0447\u043d\u0438\u043a\u0430" },
  "temp.crud.remove_rows": { file: "remove_from_user_dict.xml", description: "\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0432\u043e\u0437\u043c\u043e\u0436\u043d\u043e\u0441\u0442\u0438 \u0443\u0434\u0430\u043b\u0435\u043d\u0438\u044f \u0441\u0442\u0440\u043e\u043a \u0432 \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c\u0441\u043a\u043e\u043c \u0441\u043f\u0440\u0430\u0432\u043e\u0447\u043d\u0438\u043a\u0435" },
  "temp.crud.update": { file: "update_user_dict.xml", description: "\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0432\u043e\u0437\u043c\u043e\u0436\u043d\u043e\u0441\u0442\u0438 \u0438\u0437\u043c\u0435\u043d\u0435\u043d\u0438\u044f \u0434\u0430\u043d\u043d\u044b\u0445 \u0432 \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c\u0441\u043a\u043e\u043c \u0441\u043f\u0440\u0430\u0432\u043e\u0447\u043d\u0438\u043a\u0435" },
};

const AUTO_ERROR_DICTIONARY = [
  {
    keys: ["not found", "\u043d\u0435 \u043d\u0430\u0439\u0434", "\u043e\u0442\u0441\u0443\u0442\u0441\u0442\u0432"],
    title: "\u0421\u043f\u0440\u0430\u0432\u043e\u0447\u043d\u0438\u043a \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d",
    plain: "\u0421\u0438\u0441\u0442\u0435\u043c\u0430 \u043d\u0435 \u0441\u043c\u043e\u0433\u043b\u0430 \u043d\u0430\u0439\u0442\u0438 \u0438\u043b\u0438 \u043e\u0442\u043a\u0440\u044b\u0442\u044c \u043d\u0443\u0436\u043d\u044b\u0439 \u0441\u043f\u0440\u0430\u0432\u043e\u0447\u043d\u0438\u043a.",
    severity: "high",
    causes: [
      "\u041d\u0435\u0432\u0435\u0440\u043d\u043e \u0443\u043a\u0430\u0437\u0430\u043d \u043e\u0431\u044a\u0435\u043a\u0442 \u0438\u043b\u0438 \u043e\u043d \u043e\u0442\u0441\u0443\u0442\u0441\u0442\u0432\u0443\u0435\u0442.",
      "\u0412 \u0442\u0435\u043a\u0443\u0449\u0435\u0439 \u0441\u0431\u043e\u0440\u043a\u0435 \u0434\u0440\u0443\u0433\u043e\u0439 \u043d\u0430\u0431\u043e\u0440 \u0434\u0430\u043d\u043d\u044b\u0445.",
    ],
    action: "\u041f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 \u0438\u043c\u044f \u0438 \u043f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u0435 \u0437\u0430\u043f\u0443\u0441\u043a.",
  },
  {
    keys: ["invalid vector subscript", "vector subscript"],
    title: "\u0412\u043d\u0443\u0442\u0440\u0435\u043d\u043d\u044f\u044f \u043e\u0448\u0438\u0431\u043a\u0430 \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u043a\u0438 \u0434\u0430\u043d\u043d\u044b\u0445",
    plain: "\u0412\u043d\u0443\u0442\u0440\u0435\u043d\u043d\u044f\u044f \u043e\u0448\u0438\u0431\u043a\u0430 \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u043a\u0438 \u0434\u0430\u043d\u043d\u044b\u0445.",
    severity: "high",
    causes: [
      "\u041f\u0440\u043e\u0431\u043b\u0435\u043c\u0430 \u0432 \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u043a\u0435 \u0437\u0430\u043f\u0440\u043e\u0441\u0430 \u043d\u0430 \u0441\u0442\u043e\u0440\u043e\u043d\u0435 API.",
      "\u041d\u0435\u043a\u043e\u043d\u0441\u0438\u0441\u0442\u0435\u043d\u0442\u043d\u044b\u0435 \u0434\u0430\u043d\u043d\u044b\u0435.",
    ],
    action: "\u041f\u0435\u0440\u0435\u0434\u0430\u0439\u0442\u0435 run_id \u0440\u0430\u0437\u0440\u0430\u0431\u043e\u0442\u0447\u0438\u043a\u0443 API.",
  },
  {
    keys: ["permission denied", "access denied", "\u043d\u0435\u0434\u043e\u0441\u0442\u0430\u0442\u043e\u0447\u043d\u043e \u043f\u0440\u0430\u0432"],
    title: "\u041d\u0435\u0434\u043e\u0441\u0442\u0430\u0442\u043e\u0447\u043d\u043e \u043f\u0440\u0430\u0432 \u0434\u043e\u0441\u0442\u0443\u043f\u0430",
    plain: "\u041d\u0435\u0434\u043e\u0441\u0442\u0430\u0442\u043e\u0447\u043d\u043e \u043f\u0440\u0430\u0432 \u0434\u043e\u0441\u0442\u0443\u043f\u0430.",
    severity: "high",
    causes: [
      "\u0423 \u0443\u0447\u0451\u0442\u043d\u043e\u0439 \u0437\u0430\u043f\u0438\u0441\u0438 \u043d\u0435\u0442 \u043d\u0443\u0436\u043d\u044b\u0445 \u043f\u0440\u0430\u0432.",
      "\u041e\u0433\u0440\u0430\u043d\u0438\u0447\u0435\u043d\u0438\u044f \u043f\u0440\u0430\u0432 \u043d\u0430 \u0441\u0442\u043e\u0440\u043e\u043d\u0435 \u0441\u0438\u0441\u0442\u0435\u043c\u044b.",
    ],
    action: "\u041f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 \u0440\u043e\u043b\u044c \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044f.",
  },
];

function getStepNameByCode(code, fallbackTitle = "") {
  const key = String(code || "").toLowerCase();
  return AUTO_STEP_NAME_BY_CODE[key] || String(fallbackTitle || key || "\u0428\u0430\u0433");
}

function getXmlCheckInfo(code) {
  const key = String(code || "").toLowerCase();
  return AUTO_XML_BY_CODE[key] || null;
}

function formatDurationHuman(ms) {
  const n = Number(ms || 0);
  if (!Number.isFinite(n) || n <= 0) {
    return "0 \u0441\u0435\u043a";
  }
  if (n < 1000) {
    return `${(n / 1000).toFixed(1)} \u0441\u0435\u043a`;
  }
  if (n < 60000) {
    return `${(n / 1000).toFixed(1)} \u0441\u0435\u043a`;
  }
  const sec = Math.round(n / 1000);
  const min = Math.floor(sec / 60);
  const rem = sec % 60;
  return `${min} \u043c\u0438\u043d ${rem} \u0441\u0435\u043a`;
}

function runDurationMs(report) {
  const direct = Number(report?.duration_ms || 0);
  if (Number.isFinite(direct) && direct > 0) {
    return direct;
  }
  const started = new Date(String(report?.started_at || ""));
  const finished = new Date(String(report?.finished_at || ""));
  if (Number.isNaN(started.getTime()) || Number.isNaN(finished.getTime())) {
    return 0;
  }
  return Math.max(0, finished.getTime() - started.getTime());
}

function computeAutoStatistics(report, steps) {
  const summary = report?.summary && typeof report.summary === "object" ? report.summary : {};
  const totalFromSummary = Number(summary.total);
  const passedFromSummary = Number(summary.passed);
  const failedFromSummary = Number(summary.failed);
  const skippedFromSummary = Number(summary.skipped);

  if (
    Number.isFinite(totalFromSummary)
    && Number.isFinite(passedFromSummary)
    && Number.isFinite(failedFromSummary)
    && Number.isFinite(skippedFromSummary)
  ) {
    return {
      total_steps: Math.max(0, totalFromSummary),
      passed: Math.max(0, passedFromSummary),
      failed: Math.max(0, failedFromSummary),
      skipped: Math.max(0, skippedFromSummary),
    };
  }

  let passed = 0;
  let failed = 0;
  let skipped = 0;
  steps.forEach((s) => {
    const st = String(s?.status || "").toLowerCase();
    if (st === "passed") passed += 1;
    else if (st === "failed") failed += 1;
    else if (st === "skipped") skipped += 1;
  });

  return {
    total_steps: steps.length,
    passed,
    failed,
    skipped,
  };
}

function toStatusLabelRu(status, stats) {
  const v = String(status || "").toLowerCase();
  const passed = Number(stats?.passed || 0);
  const failed = Number(stats?.failed || 0);
  if (v === "passed") {
    return "\u0423\u0441\u043f\u0435\u0448\u043d\u043e";
  }
  if (v === "failed") {
    return "\u041e\u0448\u0438\u0431\u043a\u0430";
  }
  if (v === "skipped") {
    return "\u041f\u0440\u043e\u043f\u0443\u0449\u0435\u043d\u043e";
  }
  if (failed > 0 && passed > 0) {
    return "\u0427\u0430\u0441\u0442\u0438\u0447\u043d\u043e \u0443\u0441\u043f\u0435\u0448\u043d\u043e";
  }
  return AUTO_STATUS_LABELS[v] || "\u041f\u0440\u043e\u043f\u0443\u0449\u0435\u043d\u043e";
}

function errorHint(message) {
  const raw = String(message || "");
  const lower = raw.toLowerCase();
  const found = AUTO_ERROR_DICTIONARY.find((row) => row.keys.some((k) => lower.includes(k)));
  if (found) {
    return {
      title: found.title,
      plain_explanation: found.plain,
      severity: found.severity,
      possible_causes: [...found.causes],
      recommended_action: found.action,
    };
  }
  return {
    title: "\u0422\u0435\u0445\u043d\u0438\u0447\u0435\u0441\u043a\u0430\u044f \u043e\u0448\u0438\u0431\u043a\u0430 \u0448\u0430\u0433\u0430",
    plain_explanation: "\u0412\u043e \u0432\u0440\u0435\u043c\u044f \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u0438\u044f \u0448\u0430\u0433\u0430 \u043f\u0440\u043e\u0438\u0437\u043e\u0448\u043b\u0430 \u0442\u0435\u0445\u043d\u0438\u0447\u0435\u0441\u043a\u0430\u044f \u043e\u0448\u0438\u0431\u043a\u0430. \u0422\u0440\u0435\u0431\u0443\u0435\u0442\u0441\u044f \u0434\u043e\u043f\u043e\u043b\u043d\u0438\u0442\u0435\u043b\u044c\u043d\u0430\u044f \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430.",
    severity: "medium",
    possible_causes: [
      "\u0412\u0440\u0435\u043c\u0435\u043d\u043d\u0430\u044f \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u043d\u043e\u0441\u0442\u044c \u0441\u0435\u0440\u0432\u0438\u0441\u0430.",
      "\u041d\u0435\u0441\u0442\u0430\u043d\u0434\u0430\u0440\u0442\u043d\u044b\u0435 \u0434\u0430\u043d\u043d\u044b\u0435 \u0432 \u0441\u0431\u043e\u0440\u043a\u0435.",
      "\u0421\u0435\u0442\u0435\u0432\u0430\u044f \u043d\u0435\u0441\u0442\u0430\u0431\u0438\u043b\u044c\u043d\u043e\u0441\u0442\u044c.",
    ],
    recommended_action: "\u041f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u0435 \u0437\u0430\u043f\u0443\u0441\u043a. \u0415\u0441\u043b\u0438 \u043e\u0448\u0438\u0431\u043a\u0430 \u043f\u043e\u0432\u0442\u043e\u0440\u044f\u0435\u0442\u0441\u044f, \u043f\u0435\u0440\u0435\u0434\u0430\u0439\u0442\u0435 run_id \u0440\u0430\u0437\u0440\u0430\u0431\u043e\u0442\u0447\u0438\u043a\u0443.",
  };
}

function plainResultByStatus(status, stepName, message) {
  const st = String(status || "").toLowerCase();
  const msg = String(message || "").trim();

  if (st === "passed") {
    return `\u0428\u0430\u0433 «${stepName}» \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d \u0443\u0441\u043f\u0435\u0448\u043d\u043e.`;
  }
  if (st === "skipped") {
    return msg
      ? `\u0428\u0430\u0433 «${stepName}» \u043f\u0440\u043e\u043f\u0443\u0449\u0435\u043d: ${msg}`
      : `\u0428\u0430\u0433 «${stepName}» \u043f\u0440\u043e\u043f\u0443\u0449\u0435\u043d \u0438\u0437-\u0437\u0430 \u0443\u0441\u043b\u043e\u0432\u0438\u0439 \u0441\u0446\u0435\u043d\u0430\u0440\u0438\u044f.`;
  }
  if (st === "failed") {
    return errorHint(msg).plain_explanation;
  }
  return msg || "\u0420\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442 \u0448\u0430\u0433\u0430 \u043f\u043e\u043b\u0443\u0447\u0435\u043d.";
}

function finalConclusionByLabel(label) {
  if (label === "\u0423\u0441\u043f\u0435\u0448\u043d\u043e") return "\u0422\u0435\u0441\u0442 \u043f\u0440\u043e\u0439\u0434\u0435\u043d";
  if (label === "\u0427\u0430\u0441\u0442\u0438\u0447\u043d\u043e \u0443\u0441\u043f\u0435\u0448\u043d\u043e") return "\u0422\u0435\u0441\u0442 \u043d\u0435 \u043f\u0440\u043e\u0439\u0434\u0435\u043d";
  if (label === "\u041f\u0440\u043e\u043f\u0443\u0449\u0435\u043d\u043e") return "\u0422\u0435\u0441\u0442 \u043f\u0440\u043e\u043f\u0443\u0449\u0435\u043d";
  return "\u0422\u0435\u0441\u0442 \u043d\u0435 \u043f\u0440\u043e\u0439\u0434\u0435\u043d";
}

function buildTesterConclusion(summary, stats, mainProblems) {
  const failed = Number(stats?.failed || 0);
  const passed = Number(stats?.passed || 0);
  const total = Number(stats?.total_steps || 0);
  const skipped = Number(stats?.skipped || 0);
  const label = String(summary?.status_label || "");

  if (failed === 0 && total > 0) {
    return {
      short_text: `\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u0430 \u0443\u0441\u043f\u0435\u0448\u043d\u043e: ${passed} \u0438\u0437 ${total} \u0448\u0430\u0433\u043e\u0432 \u043f\u0440\u043e\u0448\u043b\u0438.`,
      next_steps: [
        "\u041c\u043e\u0436\u043d\u043e \u043f\u0435\u0440\u0435\u0445\u043e\u0434\u0438\u0442\u044c \u043a \u0441\u043b\u0435\u0434\u0443\u044e\u0449\u0435\u043c\u0443 \u0441\u0446\u0435\u043d\u0430\u0440\u0438\u044e.",
        "\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u0435 run_id \u0432 \u043f\u0440\u043e\u0442\u043e\u043a\u043e\u043b\u0435 \u0442\u0435\u0441\u0442\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u044f.",
      ],
    };
  }

  const topProblem = Array.isArray(mainProblems) && mainProblems.length ? mainProblems[0] : null;
  const problemText = topProblem
    ? `\u041a\u043b\u044e\u0447\u0435\u0432\u0430\u044f \u043f\u0440\u043e\u0431\u043b\u0435\u043c\u0430: ${topProblem.step_name} \u2014 ${topProblem.title}.`
    : "\u041e\u0431\u043d\u0430\u0440\u0443\u0436\u0435\u043d\u044b \u043e\u0448\u0438\u0431\u043a\u0438 \u0432\u044b\u043f\u043e\u043b\u043d\u0435\u043d\u0438\u044f.";

  return {
    short_text: `\u0422\u0435\u0441\u0442 \u043d\u0435 \u043f\u0440\u043e\u0439\u0434\u0435\u043d. \u0421\u0442\u0430\u0442\u0443\u0441: ${label}. \u041f\u0440\u043e\u0439\u0434\u0435\u043d\u043e ${passed}/${total}, \u043e\u0448\u0438\u0431\u043e\u043a: ${failed}, \u043f\u0440\u043e\u043f\u0443\u0449\u0435\u043d\u043e: ${skipped}. ${problemText}`,
    next_steps: [
      "\u041f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 \u0440\u0430\u0437\u0434\u0435\u043b sections.main_problems \u0438 \u0432\u044b\u043f\u043e\u043b\u043d\u0438\u0442\u0435 recommended_action.",
      "\u041f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u0435 \u043f\u0440\u043e\u0433\u043e\u043d \u043f\u043e\u0441\u043b\u0435 \u0438\u0441\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0439.",
      "\u0415\u0441\u043b\u0438 \u043e\u0448\u0438\u0431\u043a\u0430 \u043f\u043e\u0432\u0442\u043e\u0440\u044f\u0435\u0442\u0441\u044f, \u043f\u0435\u0440\u0435\u0434\u0430\u0439\u0442\u0435 \u0440\u0430\u0437\u0440\u0430\u0431\u043e\u0442\u0447\u0438\u043a\u0443 run_id \u0438 technical_details.",
    ],
  };
}

function renderAutoHumanSummary(report) {
  if (!el.autoHumanSummary) {
    return;
  }
  if (!report || typeof report !== "object") {
    el.autoHumanSummary.innerHTML = "";
    return;
  }

  const normalized = buildReadableAutoReport(report);
  const summary = normalized?.summary || {};
  const stats = normalized?.statistics || {};
  const problems = Array.isArray(normalized?.sections?.main_problems) ? normalized.sections.main_problems : [];

  const problemsHtml = problems.length
    ? `<ul>${problems
      .slice(0, 8)
      .map(
        (item) =>
          `<li><b>${escapeHtml(String(item.step_name || "-"))}</b>: ${escapeHtml(String(item.plain_explanation || item.error_message || ""))}</li>`,
      )
      .join("")}</ul>`
    : "<div>\u041a\u0440\u0438\u0442\u0438\u0447\u043d\u044b\u0445 \u043e\u0448\u0438\u0431\u043e\u043a \u043d\u0435 \u043e\u0431\u043d\u0430\u0440\u0443\u0436\u0435\u043d\u043e.</div>";

  const started = String(summary.started_at || "").replace("T", " ").replace("+00:00", " UTC") || "-";
  const finished = String(summary.finished_at || "").replace("T", " ").replace("+00:00", " UTC") || "-";

  el.autoHumanSummary.innerHTML = `
    <div><b>\u0421\u043f\u0440\u0430\u0432\u043e\u0447\u043d\u0438\u043a:</b> ${escapeHtml(String(summary.object_name || "-"))}</div>
    <div><b>\u0421\u0442\u0430\u0442\u0443\u0441 \u043f\u0440\u043e\u0433\u043e\u043d\u0430:</b> ${escapeHtml(String(summary.status_label || "-"))} | <b>\u0428\u0430\u0433\u043e\u0432:</b> ${Number(stats.total_steps || 0)} | <b>\u041f\u0440\u043e\u0439\u0434\u0435\u043d\u043e:</b> ${Number(stats.passed || 0)} | <b>\u041e\u0448\u0438\u0431\u043e\u043a:</b> ${Number(stats.failed || 0)} | <b>\u041f\u0440\u043e\u043f\u0443\u0449\u0435\u043d\u043e:</b> ${Number(stats.skipped || 0)}</div>
    <div><b>\u0412\u0440\u0435\u043c\u044f:</b> ${escapeHtml(started)} \u2192 ${escapeHtml(finished)} | <b>\u0414\u043b\u0438\u0442\u0435\u043b\u044c\u043d\u043e\u0441\u0442\u044c:</b> ${escapeHtml(String(summary.duration_human || "0 \u0441\u0435\u043a"))}</div>
    <div><b>\u0418\u0442\u043e\u0433:</b> ${escapeHtml(String(summary.final_conclusion || "-"))}</div>
    <div><b>\u0414\u0435\u0442\u0430\u043b\u0438 \u043e\u0448\u0438\u0431\u043e\u043a:</b></div>
    ${problemsHtml}
  `;
}

function extractSnapshotFromReport(report) {
  if (!report || typeof report !== "object") {
    return null;
  }
  const steps = Array.isArray(report.steps) ? report.steps : [];
  const preferredCodes = ["source.query", "source.select_fields", "source.search"];
  let chosenStep = null;
  for (const code of preferredCodes) {
    chosenStep = steps.find((step) => String(step?.code || "") === code && String(step?.status || "").toLowerCase() === "passed");
    if (chosenStep) {
      break;
    }
  }
  if (!chosenStep) {
    return null;
  }

  const result = chosenStep?.result && typeof chosenStep.result === "object" ? chosenStep.result : {};
  const rows = Array.isArray(result.rows) ? result.rows : [];
  const rowsSafe = rows.filter((row) => row && typeof row === "object");
  const columns = Array.isArray(result.columns) && result.columns.length
    ? result.columns.map((col) => String(col || "").trim()).filter(Boolean)
    : inferColumns(rowsSafe);
  const foundCount = Number(result.found_count ?? rowsSafe.length ?? 0);

  return {
    stepCode: String(chosenStep.code || ""),
    stepTitle: String(chosenStep.title || ""),
    durationMs: Number(chosenStep.duration_ms || 0),
    dictName: String(report.source_dict_name || result.dict_name || ""),
    columns,
    rows: rowsSafe,
    foundCount,
  };
}

function renderAutoDictSnapshot(report) {
  if (!el.autoDictSnapshotMeta || !el.autoDictSnapshotTable) {
    return;
  }
  const snapshot = extractSnapshotFromReport(report);
  if (!snapshot) {
    el.autoDictSnapshotMeta.textContent =
      "Снимок недоступен: в отчёте нет успешного шага source.query/select_fields/search.";
    renderDataTable(el.autoDictSnapshotTable, ["Состояние"], [{ "Состояние": "Нет данных для отображения" }]);
    return;
  }

  const MAX_ROWS = 80;
  const rowsTotal = snapshot.rows.length;
  const rowsPreview = snapshot.rows.slice(0, MAX_ROWS);
  const columns = snapshot.columns.length ? snapshot.columns : inferColumns(rowsPreview);
  const previewRows = rowsPreview.map((row, idx) => {
    const normalized = { "№": idx + 1 };
    columns.forEach((col) => {
      const value = row?.[col];
      normalized[col] = value === undefined || value === null ? "" : value;
    });
    return normalized;
  });
  const durationSec = snapshot.durationMs > 0 ? (snapshot.durationMs / 1000).toFixed(1) : "0.0";

  el.autoDictSnapshotMeta.textContent =
    `Справочник: ${snapshot.dictName || "-"} | Шаг: ${snapshot.stepCode} (${snapshot.stepTitle || "-"}) | ` +
    `Найдено строк: ${snapshot.foundCount} | Показано: ${rowsPreview.length}${rowsTotal > MAX_ROWS ? ` из ${rowsTotal}` : ""} | ` +
    `Время шага: ${durationSec} c`;

  renderDataTable(el.autoDictSnapshotTable, ["№", ...columns], previewRows);
}

function buildReadableAutoReport(report) {
  if (!report || typeof report !== "object") {
    return {
      report_type: "test_execution_report",
      report_version: "2.0",
      summary: {
        status: "unknown",
        status_label: "\u041f\u0440\u043e\u043f\u0443\u0449\u0435\u043d\u043e",
        object_name: "",
        started_at: "",
        finished_at: "",
        duration_ms: 0,
        duration_human: "0 \u0441\u0435\u043a",
        target_name: "",
        mode: "",
        final_conclusion: "\u0422\u0435\u0441\u0442 \u043f\u0440\u043e\u043f\u0443\u0449\u0435\u043d",
      },
      statistics: {
        total_steps: 0,
        passed: 0,
        failed: 0,
        skipped: 0,
      },
      sections: {
        main_problems: [],
        step_results: [],
      },
      tester_conclusion: {
        short_text: "\u041e\u0442\u0447\u0451\u0442 \u043f\u0443\u0441\u0442. \u041d\u0435\u0442 \u0434\u0430\u043d\u043d\u044b\u0445 \u0434\u043b\u044f \u0430\u043d\u0430\u043b\u0438\u0437\u0430.",
        next_steps: ["\u041f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u0435 \u0437\u0430\u043f\u0443\u0441\u043a \u0430\u0432\u0442\u043e\u0442\u0435\u0441\u0442\u0430 \u0438 \u043e\u0442\u043a\u0440\u043e\u0439\u0442\u0435 \u043e\u0442\u0447\u0451\u0442 \u0441\u043d\u043e\u0432\u0430."],
      },
      technical_details: {
        run_id: "",
        target_id: null,
        started_at: "",
        finished_at: "",
        status: "unknown",
        source_dict_name: "",
        raw_failed_steps: [],
        raw_steps: [],
      },
    };
  }

  const steps = Array.isArray(report.steps) ? report.steps.filter((s) => s && typeof s === "object") : [];
  const stats = computeAutoStatistics(report, steps);
  const durationMs = runDurationMs(report);
  const status = String(report.status || "unknown").toLowerCase();
  const statusLabel = toStatusLabelRu(status, stats);

  const stepResults = steps.map((step, idx) => {
    const technicalCode = String(step.code || "");
    const stepName = getStepNameByCode(technicalCode, String(step.title || ""));
    const stepStatus = String(step.status || "").toLowerCase();
    const stepStatusLabel = AUTO_STATUS_LABELS[stepStatus] || "\u041f\u0440\u043e\u043f\u0443\u0449\u0435\u043d\u043e";
    const durationStepMs = Number(step.duration_ms || 0);
    const resultMessage = String(step.message || "");
    const xmlInfo = getXmlCheckInfo(technicalCode);
    const xmlName = xmlInfo?.file || "";

    return {
      order: idx + 1,
      scope: String(step.scope || ""),
      step_name: stepName,
      technical_code: technicalCode,
      xml_request: xmlName,
      status: stepStatus,
      status_label: stepStatusLabel,
      duration_ms: Number.isFinite(durationStepMs) ? durationStepMs : 0,
      duration_human: formatDurationHuman(durationStepMs),
      result_message: resultMessage,
      plain_result: plainResultByStatus(stepStatus, stepName, resultMessage),
    };
  });

  const failedSource = Array.isArray(report.failed_steps) && report.failed_steps.length
    ? report.failed_steps.filter((s) => s && typeof s === "object")
    : stepResults
      .filter((s) => s.status === "failed")
      .map((s) => ({
        code: s.technical_code,
        title: s.step_name,
        message: s.result_message,
      }));

  const mainProblems = failedSource.map((failed, idx) => {
    const technicalCode = String(failed.code || "");
    const stepName = getStepNameByCode(technicalCode, String(failed.title || ""));
    const errorMessage = String(failed.message || "");
    const hint = errorHint(errorMessage);

    return {
      id: idx + 1,
      title: hint.title,
      step_name: stepName,
      technical_code: technicalCode,
      severity: hint.severity,
      error_message: errorMessage,
      plain_explanation: hint.plain_explanation,
      possible_causes: hint.possible_causes,
      recommended_action: hint.recommended_action,
    };
  });

  const summary = {
    status,
    status_label: statusLabel,
    object_name: String(report.source_dict_name || ""),
    started_at: String(report.started_at || ""),
    finished_at: String(report.finished_at || ""),
    duration_ms: durationMs,
    duration_human: formatDurationHuman(durationMs),
    target_name: String(report.target_name || ""),
    mode: String(report.mode || ""),
    final_conclusion: finalConclusionByLabel(statusLabel),
  };

  return {
    report_type: "test_execution_report",
    report_version: "2.0",
    summary,
    statistics: stats,
    sections: {
      main_problems: mainProblems,
      step_results: stepResults,
    },
    tester_conclusion: buildTesterConclusion(summary, stats, mainProblems),
    technical_details: {
      run_id: String(report.run_id || ""),
      target_id: report.target_id ?? null,
      started_at: String(report.started_at || ""),
      finished_at: String(report.finished_at || ""),
      status,
      source_dict_name: String(report.source_dict_name || ""),
      raw_failed_steps: failedSource,
      raw_steps: steps.map((step) => ({
        scope: String(step.scope || ""),
        code: String(step.code || ""),
        title: String(step.title || ""),
        status: String(step.status || ""),
        duration_ms: Number(step.duration_ms || 0),
        message: String(step.message || ""),
      })),
    },
  };
}

async function handleAutoOpenReport(runId) {
  if (!runId) {
    return;
  }
  if (state.autoOpenReportInFlight) {
    return;
  }
  if (state.autoLastOpenedRunId === runId && state.autoCurrentReport?.run_id === runId) {
    return;
  }

  state.autoOpenReportInFlight = true;
  state.autoLastOpenedRunId = runId;
  try {
    const report = await apiRequest(`/dicts/autotest/reports/${encodeURIComponent(runId)}`);
    state.autoCurrentReport = report;
    renderAutoHumanSummary(report);
    setJson(el.autoReportJson, buildReadableAutoReport(report));
    renderAutoSteps(Array.isArray(report?.steps) ? report.steps : []);
    renderAutoDictSnapshot(report);
  } catch (error) {
    toast(`Не удалось открыть отчёт ${runId}: ${error.message}`, "error");
  } finally {
    state.autoOpenReportInFlight = false;
  }
}

function renderAutoSteps(steps) {
  const scopeLabel = (scope) => {
    const v = String(scope || "").toLowerCase();
    if (v === "preinstalled") return "\u041f\u0440\u0435\u0434\u0443\u0441\u0442\u0430\u043d\u043e\u0432\u043b\u0435\u043d\u043d\u044b\u0439";
    if (v === "temporary") return "\u0412\u0440\u0435\u043c\u0435\u043d\u043d\u044b\u0439";
    return v || "-";
  };

  const rows = steps.map((step) => {
    const code = String(step?.code || "");
    const xmlInfo = getXmlCheckInfo(code);
    const xmlLabel = xmlInfo?.description || getStepNameByCode(code, String(step?.title || ""));

    return {
      "\u0422\u0438\u043f \u0448\u0430\u0433\u0430": scopeLabel(step?.scope || ""),
      "\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430": xmlLabel,
      "\u0420\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442": formatStepStatus(step?.status || ""),
      "\u0412\u0440\u0435\u043c\u044f": formatDurationHuman(Number(step?.duration_ms || 0)),
      "\u041a\u043e\u043c\u043c\u0435\u043d\u0442\u0430\u0440\u0438\u0439": String(step?.message || ""),
    };
  });

  renderDataTable(
    el.autoStepsTable,
    [
      "\u0422\u0438\u043f \u0448\u0430\u0433\u0430",
      "\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430",
      "\u0420\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442",
      "\u0412\u0440\u0435\u043c\u044f",
      "\u041a\u043e\u043c\u043c\u0435\u043d\u0442\u0430\u0440\u0438\u0439",
    ],
    rows,
  );
}

function formatStepStatus(raw) {
  const value = String(raw || "").toLowerCase();
  if (value === "passed") return "Успешно";
  if (value === "failed") return "Ошибка";
  if (value === "cancelled") return "Остановлен";
  if (value === "skipped") return "Пропущено";
  return value || "-";
}

function getAutoSourceDictName() {
  const fromInput = String(el.udDictName?.value || "").trim();
  if (fromInput) {
    return fromInput;
  }
  const fromSelect = String(el.autoSourceDict?.value || "").trim();
  if (fromSelect) {
    return fromSelect;
  }
  throw new Error("Укажите справочник для автотеста: выберите из списка или введите вручную.");
}

function renderAutoProgress(job) {
  if (!el.autoRunStatus || !job || typeof job !== "object") {
    return;
  }
  const progress = job.progress && typeof job.progress === "object" ? job.progress : {};
  const percent = Number(progress.percent || 0);
  const completed = Number(progress.completed_steps || 0);
  const total = Number(progress.total_steps || 0);
  const passed = Number(progress.passed || 0);
  const failed = Number(progress.failed || 0);
  const skipped = Number(progress.skipped || 0);
  const current = progress.current_step && typeof progress.current_step === "object" ? progress.current_step : null;
  const stepTitle = current?.title ? ` | шаг: ${current.title}` : "";
  const msg = current?.message ? ` | ${current.message}` : "";
  const elapsedSec = (Date.now() - (state.autoRunStartedAtMs || Date.now())) / 1000;
  el.autoRunStatus.dataset.state = "running";
  el.autoRunStatus.textContent =
    `Автотест ${percent}% (${completed}/${total}), пройдено=${passed}, ошибок=${failed}, пропущено=${skipped}, t=${formatElapsed(elapsedSec)}${stepTitle}${msg}`;
}

async function finalizeAutoRunJob(job) {
  const report = job?.report && typeof job.report === "object" ? job.report : null;
  if (report) {
    state.autoCurrentReport = report;
    renderAutoHumanSummary(report);
    setJson(el.autoReportJson, buildReadableAutoReport(report));
    renderAutoSteps(Array.isArray(report?.steps) ? report.steps : []);
    renderAutoDictSnapshot(report);
  } else if (job?.run_id) {
    await handleAutoOpenReport(String(job.run_id));
  } else {
    renderAutoDictSnapshot(null);
  }

  await handleAutoLoadReports();

  await maybeDownloadRunArtifacts(report || state.autoCurrentReport || null);

  const finalReport = report || state.autoCurrentReport || {};
  const summary = finalReport?.summary || {};
  const failed = Number(summary.failed || 0);
  const status = String(job?.status || finalReport?.status || "").toLowerCase();
  const message = status === "cancelled"
    ? "Автотест остановлен пользователем"
    : status === "passed" && failed === 0
    ? "Автотест завершён успешно"
    : (job?.error ? `Автотест завершился с ошибкой: ${job.error}` : `Автотест завершён, ошибок: ${failed}`);
  setAutoRunUiStateIdle(
    message,
    status === "cancelled" ? "idle" : (status === "passed" && failed === 0 ? "ok" : "error"),
  );
}

async function maybeDownloadRunArtifacts(report) {
  if (!report || typeof report !== "object") {
    return;
  }
  const runId = String(report.run_id || "").trim();
  if (!runId || state.autoArtifactsDownloadedRunId === runId) {
    return;
  }
  const artifacts = Array.isArray(report.artifacts) ? report.artifacts : [];
  if (!artifacts.length) {
    return;
  }

  let downloaded = 0;
  for (const item of artifacts) {
    const artifactId = String(item?.id || "").trim();
    const filename = String(item?.filename || "").trim() || `${artifactId}.bin`;
    if (!artifactId) {
      continue;
    }
    try {
      const { blob } = await apiBinaryRequest(
        `/dicts/autotest/reports/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactId)}/download`,
      );
      downloadBlob(blob, filename);
      downloaded += 1;
    } catch (error) {
      console.warn("Failed to auto-download artifact", { runId, artifactId, error });
    }
  }
  state.autoArtifactsDownloadedRunId = runId;
  if (downloaded > 0) {
    toast(`Скачано артефактов: ${downloaded}`, "ok");
  }
}

async function pollAutoRunJob(jobId) {
  if (!jobId || !state.autoRunInFlight) {
    return;
  }
  if (state.autoRunPollInFlight) {
    return;
  }
  state.autoRunPollInFlight = true;
  try {
    const payload = await apiRequest(`/dicts/autotest/jobs/${encodeURIComponent(jobId)}`);
    const job = payload?.job;
    if (!job) {
      throw new Error("Сервер не вернул состояние job.");
    }
    renderAutoProgress(job);
    const status = String(job.status || "").toLowerCase();
    if (status === "passed" || status === "failed" || status === "cancelled") {
      await finalizeAutoRunJob(job);
    }
  } catch (error) {
    stopAutoRunPolling();
    setAutoRunUiStateIdle(`Ошибка опроса автотеста: ${error.message}`, "error");
    toast(error.message, "error");
  } finally {
    state.autoRunPollInFlight = false;
  }
}

async function handleAutoRun() {
  if (state.autoRunInFlight) {
    toast("Автотест уже выполняется. Дождитесь завершения.", "error");
    return;
  }

  try {
    const sourceDict = getAutoSourceDictName();
    const hasLoadedSelectValue = String(el.autoSourceDict?.value || "").trim().length > 0;
    if (!hasLoadedSelectValue && String(el.udDictName?.value || "").trim()) {
      toast("Список не загружен: автотест запущен по ручному имени справочника.", "ok");
    }
    el.udDictName.value = sourceDict;
    setAutoRunUiStateRunning(sourceDict);

    const body = {
      source_dict_name: sourceDict,
      include_create_delete: !!el.autoIncludeCrud.checked,
      include_all_types_smoke: !!el.autoIncludeAllTypes.checked,
      verbose_steps: !!el.autoVerboseSteps.checked,
      test_prefix: "autotest",
    };

    const response = await apiRequest("/dicts/autotest/run-async", {
      method: "POST",
      body,
    });
    const job = response?.job;
    if (!job?.job_id) {
      throw new Error("Сервер не вернул job_id.");
    }

    state.autoRunJobId = String(job.job_id);
    renderAutoProgress(job);

    if (state.autoRunPollTimerId != null) {
      window.clearInterval(state.autoRunPollTimerId);
    }
    state.autoRunPollTimerId = window.setInterval(() => {
      pollAutoRunJob(state.autoRunJobId);
    }, 1200);
    await pollAutoRunJob(state.autoRunJobId);

    toast(response?.already_running ? "Автотест уже запущен на этой цели" : "Автотест запущен в фоне", "ok");
  } catch (error) {
    toast(error.message, "error");
    setAutoRunUiStateIdle(`Ошибка автотеста: ${error.message}`, "error");
  }
}

function normalizeApiBase(raw) {
  const value = String(raw || "").trim().replace(/\/+$/, "");
  return value;
}

function getApiBase() {
  const nextBase = normalizeApiBase(el.apiBase.value || state.apiBase);
  if (!nextBase) {
  throw new Error("Backend URL не задан.");
  }
  state.apiBase = nextBase;
  return nextBase;
}

function looksLikeMojibake(text) {
  const value = String(text || "");
  if (!value) {
    return false;
  }
  // Only strong mojibake markers: rare cyrillic symbols or latin UTF-8 fragments.
  // Do not use broad "Рx/Сx" heuristics because they can match normal Russian text.
  if (/[ЃѓЉЊЋЌЎЏђѓљњћќўџ]/.test(value)) {
    return true;
  }
  return /(?:Ð.|Ñ.){2,}|[ÃÂ]/.test(value);
}

function repairMojibakeString(text) {
  const value = String(text || "");
  if (!value || !looksLikeMojibake(value)) {
    return value;
  }
  const score = (candidate) => {
    const raw = String(candidate || "");
    if (!raw) {
      return Number.NEGATIVE_INFINITY;
    }
    const cyr = (raw.match(/[А-Яа-яЁё]/g) || []).length;
    const bad = (raw.match(/[ЃѓЉЊЋЌЎЏђѓљњћќўџ]|(?:Ð.|Ñ.)|[ÃÂ]/g) || []).length;
    const repl = (raw.match(/�/g) || []).length;
    return cyr * 3 - bad * 4 - repl * 6;
  };
  const best = {
    text: value,
    score: score(value),
  };
  const decodeAsUtf8FromByteMap = (input) => {
    try {
      const cp1251Decoder = new TextDecoder("windows-1251");
      const map = new Map();
      for (let i = 0; i < 256; i += 1) {
        map.set(cp1251Decoder.decode(new Uint8Array([i])), i);
      }
      const byteList = [];
      for (const ch of String(input || "")) {
        const byte = map.get(ch);
        if (typeof byte !== "number") {
          return "";
        }
        byteList.push(byte);
      }
      return new TextDecoder("utf-8", { fatal: false }).decode(new Uint8Array(byteList));
    } catch {
      return "";
    }
  };
  const decodeLatin1AsUtf8 = (input) => {
    try {
      const bytes = [];
      for (let i = 0; i < String(input || "").length; i += 1) {
        const code = String(input || "").charCodeAt(i);
        if (code > 255) {
          return "";
        }
        bytes.push(code);
      }
      if (!bytes.length) {
        return "";
      }
      return new TextDecoder("utf-8", { fatal: false }).decode(new Uint8Array(bytes));
    } catch {
      return "";
    }
  };
  const promote = (candidate) => {
    const normalized = String(candidate || "");
    if (!normalized || normalized.includes("�")) {
      return;
    }
    const nextScore = score(normalized);
    if (nextScore > best.score && nextScore >= 1) {
      best.text = normalized;
      best.score = nextScore;
    }
  };
  const pass1 = decodeAsUtf8FromByteMap(value);
  promote(pass1);
  promote(decodeLatin1AsUtf8(value));
  if (pass1) {
    promote(decodeAsUtf8FromByteMap(pass1));
    promote(decodeLatin1AsUtf8(pass1));
  }
  return best.text;
}

function repairMojibakeDom(root) {
  if (!root) {
    return;
  }
  const walkNode = (node) => {
    if (!node) {
      return;
    }
    if (node.nodeType === Node.TEXT_NODE) {
      const fixed = repairMojibakeString(node.nodeValue || "");
      if (fixed !== node.nodeValue) {
        node.nodeValue = fixed;
      }
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) {
      return;
    }
    const tag = String(node.tagName || "").toUpperCase();
    if (tag === "SCRIPT" || tag === "STYLE") {
      return;
    }
    ["placeholder", "title", "aria-label"].forEach((attr) => {
      if (node.hasAttribute && node.hasAttribute(attr)) {
        const raw = node.getAttribute(attr) || "";
        const fixed = repairMojibakeString(raw);
        if (fixed !== raw) {
          node.setAttribute(attr, fixed);
        }
      }
    });
    const children = Array.from(node.childNodes || []);
    children.forEach((child) => walkNode(child));
  };
  walkNode(root);
}

function startMojibakeAutoRepair() {
  // Disabled by default: aggressive DOM mutation may corrupt already-correct Russian UI text.
  // Enable only for explicit diagnostics:
  // localStorage.setItem("par_test_enable_dom_mojibake_repair", "1")
  let enabled = false;
  try {
    enabled = window.localStorage?.getItem("par_test_enable_dom_mojibake_repair") === "1";
  } catch {
    enabled = false;
  }
  if (!enabled) {
    return;
  }
  const run = () => {
    repairMojibakeDom(document.body);
  };
  run();
  if (window.__mojibakeObserverStarted) {
    return;
  }
  window.__mojibakeObserverStarted = true;
  const observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
      if (mutation.type === "characterData") {
        repairMojibakeDom(mutation.target);
        return;
      }
      Array.from(mutation.addedNodes || []).forEach((node) => repairMojibakeDom(node));
      if (mutation.type === "attributes" && mutation.target) {
        repairMojibakeDom(mutation.target);
      }
    });
  });
  observer.observe(document.documentElement || document.body, {
    childList: true,
    subtree: true,
    characterData: true,
    attributes: true,
    attributeFilter: ["placeholder", "title", "aria-label"],
  });
}

function repairMojibakeDeep(value) {
  if (typeof value === "string") {
    return repairMojibakeString(value);
  }
  if (Array.isArray(value)) {
    return value.map((item) => repairMojibakeDeep(item));
  }
  if (value && typeof value === "object") {
    const out = {};
    Object.entries(value).forEach(([k, v], index) => {
      const fixedKey = repairMojibakeString(String(k || ""));
      let key = fixedKey || String(k || "");
      if (Object.prototype.hasOwnProperty.call(out, key)) {
        key = `${key}__${index}`;
      }
      out[key] = repairMojibakeDeep(v);
    });
    return out;
  }
  return value;
}

async function apiRequest(path, options = {}) {
  const apiStartedAt = performance.now();
  const base = getApiBase();
  const queryPayload = { ...(options.query || {}) };
  if (state.targetId != null && !options.skipTarget) {
    queryPayload.target_id = state.targetId;
  }
  const query = buildQuery(queryPayload);
  const url = `${base}${path}${query}`;

  const init = {
    method: options.method || "GET",
    headers: {},
  };

  if (options.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body);
  }

  if (state.targetId != null && !options.skipTarget) {
    init.headers["X-Target-ID"] = String(state.targetId);
  }

  const method = String(init.method || "GET").toUpperCase();
  const requestTimeoutMs = Math.max(1000, Number(options.timeoutMs) || REQUEST_TIMEOUT_MS);
  const maxAttempts = method === "GET" ? 2 : 1;
  let lastError = null;

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), requestTimeoutMs);
    let response;

    try {
      response = await fetch(url, { ...init, signal: controller.signal });
      const text = await response.text();
      let payload = text;

      if (text) {
        try {
          payload = JSON.parse(text);
        } catch {
          payload = text;
        }
      }
      payload = repairMojibakeDeep(payload);

      if (!response.ok) {
        const msg = typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
        const requestError = new Error(`${response.status} ${response.statusText}: ${msg}`);
        const canRetry =
          method === "GET" &&
          attempt < maxAttempts &&
          RETRYABLE_HTTP_STATUSES.has(Number(response.status));
        if (canRetry) {
          await sleep(250 * attempt);
          continue;
        }
        throw requestError;
      }

      recordApiPerf(method, path, performance.now() - apiStartedAt, true);
      return payload;
    } catch (error) {
      const isAbort = error?.name === "AbortError";
      const wrapped = isAbort
        ? new Error(`Request timeout after ${Math.floor(requestTimeoutMs / 1000)}s: ${method} ${path}`)
        : error;
      lastError = wrapped;
      const canRetry = method === "GET" && attempt < maxAttempts;
      if (!canRetry) {
        recordApiPerf(method, path, performance.now() - apiStartedAt, false);
        throw wrapped;
      }
      await sleep(250 * attempt);
    } finally {
      window.clearTimeout(timeoutId);
    }
  }

  recordApiPerf(method, path, performance.now() - apiStartedAt, false);
  throw lastError || new Error(`Request failed: ${method} ${path}`);
}

async function apiBinaryRequest(path, options = {}) {
  const apiStartedAt = performance.now();
  const base = getApiBase();
  const queryPayload = { ...(options.query || {}) };
  if (state.targetId != null && !options.skipTarget) {
    queryPayload.target_id = state.targetId;
  }
  const query = buildQuery(queryPayload);
  const url = `${base}${path}${query}`;

  const init = {
    method: options.method || "GET",
    headers: {},
  };
  if (options.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body);
  }
  if (state.targetId != null && !options.skipTarget) {
    init.headers["X-Target-ID"] = String(state.targetId);
  }

  const requestTimeoutMs = Math.max(1000, Number(options.timeoutMs) || REQUEST_TIMEOUT_MS);
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), requestTimeoutMs);
  try {
    const response = await fetch(url, { ...init, signal: controller.signal });
    if (!response.ok) {
      const text = repairMojibakeString(await response.text());
      throw new Error(text || `HTTP ${response.status}`);
    }
    const blob = await response.blob();
    const cd = String(response.headers.get("content-disposition") || "");
    let filename = "";
    const m = cd.match(/filename=\"?([^\";]+)\"?/i);
    if (m && m[1]) {
      filename = m[1];
    }
    recordApiPerf(init.method, path, performance.now() - apiStartedAt, true);
    return { blob, filename };
  } catch (error) {
    if (error?.name === "AbortError") {
      recordApiPerf(init.method, path, performance.now() - apiStartedAt, false);
      const timeoutSec = Math.max(1, Math.ceil(requestTimeoutMs / 1000));
      throw new Error(`Request timeout after ${timeoutSec}s: ${init.method} ${path}`);
    }
    recordApiPerf(init.method, path, performance.now() - apiStartedAt, false);
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

function downloadBlob(blob, filename = "download.bin") {
  const safeName = String(filename || "").trim() || "download.bin";
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = safeName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 800);
}

async function fileToBase64(file) {
  const buffer = await file.arrayBuffer();
  let binary = "";
  const bytes = new Uint8Array(buffer);
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    const part = bytes.subarray(i, i + chunk);
    binary += String.fromCharCode(...part);
  }
  return window.btoa(binary);
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function pushPerfItem(target, item) {
  target.push(item);
  if (target.length > PERF_MAX_ITEMS) {
    target.splice(0, target.length - PERF_MAX_ITEMS);
  }
}

function recordUiActionPerf(name, durationMs, ok) {
  pushPerfItem(state.perfUiActions, {
    ts: new Date().toISOString(),
    name: String(name || "").trim() || "ui-action",
    durationMs: Number(durationMs) || 0,
    ok: Boolean(ok),
  });
}

function recordApiPerf(method, path, durationMs, ok) {
  pushPerfItem(state.perfApiCalls, {
    ts: new Date().toISOString(),
    method: String(method || "GET").toUpperCase(),
    path: String(path || "").trim(),
    durationMs: Number(durationMs) || 0,
    ok: Boolean(ok),
  });
}

function topClientPerf(source, keyBuilder, limit = 5) {
  const grouped = new Map();
  source.forEach((item) => {
    const key = keyBuilder(item);
    if (!grouped.has(key)) {
      grouped.set(key, []);
    }
    grouped.get(key).push(item.durationMs);
  });
  return Array.from(grouped.entries())
    .map(([key, values]) => {
      const count = values.length;
      const total = values.reduce((acc, v) => acc + v, 0);
      const max = Math.max(...values);
      return {
        name: key,
        count,
        avgMs: Math.round((total / count) * 100) / 100,
        maxMs: Math.round(max * 100) / 100,
      };
    })
    .sort((a, b) => (b.avgMs - a.avgMs) || (b.maxMs - a.maxMs))
    .slice(0, Math.max(1, Number(limit) || 5));
}

if (typeof window !== "undefined") {
  window.parTestPerfTop5 = async () => {
    const uiTop = topClientPerf(
      state.perfUiActions,
      (x) => String(x.name || "ui-action"),
      5,
    );
    const apiTop = topClientPerf(
      state.perfApiCalls,
      (x) => `${String(x.method || "GET")} ${String(x.path || "")}`,
      5,
    );
    let backend = null;
    try {
      backend = await apiRequest("/debug/perf/summary", {
        skipTarget: true,
        query: { limit: 5, recent_limit: 50 },
        timeoutMs: 5000,
      });
    } catch (error) {
      backend = { error: error.message };
    }
    console.group("parTestPerfTop5");
    console.table(uiTop);
    console.table(apiTop);
    if (backend?.top_endpoints) {
      console.table(backend.top_endpoints);
    }
    if (backend?.top_operations) {
      console.table(backend.top_operations);
    }
    if (backend?.error) {
      console.warn("backend perf unavailable:", backend.error);
    }
    console.groupEnd();
    return { uiTop, apiTop, backend };
  };
}

function buildQuery(params) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") {
      return;
    }
    search.set(key, String(value));
  });
  const query = search.toString();
  return query ? `?${query}` : "";
}

function toast(message, type = "ok") {
  el.toast.className = "";
  el.toast.classList.add("show", type);
  el.toast.textContent = repairMojibakeString(String(message || ""));
  window.clearTimeout(toast._timer);
  toast._timer = window.setTimeout(() => {
    el.toast.className = "";
  }, 3200);
}

function setJson(preElement, payload) {
  if (!preElement) {
    return;
  }
  const sanitize = (value, depth = 0) => {
    if (depth > 8) {
      return "[depth-truncated]";
    }
    if (typeof value === "string") {
      const fixed = repairMojibakeString(value);
      return truncateForUi(fixed, 6000);
    }
    if (Array.isArray(value)) {
      const capped = value.slice(0, 80).map((item) => sanitize(item, depth + 1));
      if (value.length > 80) {
        capped.push(`... [${value.length - 80} more items truncated]`);
      }
      return capped;
    }
    if (value && typeof value === "object") {
      const out = {};
      const entries = Object.entries(value);
      entries.slice(0, 120).forEach(([key, item], index) => {
        const fixedKey = repairMojibakeString(String(key || ""));
        let outKey = fixedKey || String(key || "");
        if (Object.prototype.hasOwnProperty.call(out, outKey)) {
          outKey = `${outKey}__${index}`;
        }
        out[outKey] = sanitize(item, depth + 1);
      });
      if (entries.length > 120) {
        out.__truncated__ = `... [${entries.length - 120} more keys truncated]`;
      }
      return out;
    }
    return value;
  };
  const raw = JSON.stringify(sanitize(payload), null, 2);
  const maxChars = 160000;
  if (raw.length <= maxChars) {
    preElement.textContent = raw;
    preElement.scrollTop = 0;
    preElement.scrollLeft = 0;
    return;
  }
  preElement.textContent =
    `${raw.slice(0, maxChars)}\n\n... [output truncated: ${raw.length - maxChars} chars hidden for UI stability]`;
  preElement.scrollTop = 0;
  preElement.scrollLeft = 0;
}

function truncateForUi(value, maxChars = 4000) {
  const text = String(value ?? "");
  if (text.length <= maxChars) {
    return text;
  }
  return `${text.slice(0, maxChars)} ... [truncated ${text.length - maxChars} chars]`;
}

function parseHttpErrorMessage(error) {
  const raw = String(error?.message || error || "").trim();
  if (!raw) {
    return { raw: "Request failed", statusCode: null, detail: "Request failed", source: "test_system" };
  }

  const statusMatch = raw.match(/^(\d{3})\s/i);
  const statusCode = statusMatch ? Number.parseInt(statusMatch[1], 10) : null;
  let detail = raw;

  const jsonStart = raw.indexOf("{");
  if (jsonStart >= 0) {
    const maybeJson = raw.slice(jsonStart);
    try {
      const parsed = JSON.parse(maybeJson);
      if (parsed && typeof parsed === "object" && parsed.detail) {
        detail = String(parsed.detail);
      }
    } catch {
      // keep raw detail when payload is not valid JSON
    }
  }

  let source = "test_system";
  const detailLower = detail.toLowerCase();
  if (
    detailLower.includes("paragraph api/integrator")
    || detailLower.includes("source: paragraph")
    || detailLower.includes("ishd")
    || detailLower.includes("integrator")
  ) {
    source = "paragraph_api";
  }

  return {
    raw: repairMojibakeString(raw),
    statusCode,
    detail: repairMojibakeString(detail),
    source,
  };
}

function resetFileInputSelection() {
  if (!el.fileUploadInput) {
    return;
  }
  el.fileUploadInput.value = "";
  if (el.fileUploadInput.value) {
    // Fallback for browser-specific quirks when value is not reset by assignment.
    const originalType = el.fileUploadInput.type;
    el.fileUploadInput.type = "text";
    el.fileUploadInput.type = originalType;
    el.fileUploadInput.value = "";
  }
  el.fileUploadInput.dispatchEvent(new Event("change", { bubbles: true }));
}

function getRequiredDictName() {
  const name = String(el.udDictName.value || "").trim();
  if (!name) {
    throw new Error("Введите название справочника.");
  }
  return name;
}

function addFilterRow(container, initial = {}) {
  if (!container) {
    return;
  }
  const row = document.createElement("div");
  row.className = "filter-row";
  row.innerHTML = `
    <input type="text" class="flt-column" placeholder="column" value="${escapeHtml(initial.column || "")}" />
    <select class="flt-condition">
      ${FILTER_CONDITIONS.map((c) => `<option value="${c}">${c}</option>`).join("")}
    </select>
    <input type="text" class="flt-value" placeholder="value" value="${escapeHtml(initial.value || "")}" />
    <button class="icon-btn" type="button">×</button>
  `;
  row.querySelector(".flt-condition").value = initial.condition || DEFAULT_FILTER_CONDITION;
  row.querySelector(".icon-btn").addEventListener("click", () => row.remove());
  container.appendChild(row);
}

function readFilters(container) {
  if (!container) {
    return [];
  }
  return Array.from(container.querySelectorAll(".filter-row"))
    .map((row) => {
      const column = row.querySelector(".flt-column").value.trim();
      const condition = row.querySelector(".flt-condition").value.trim() || DEFAULT_FILTER_CONDITION;
      const value = row.querySelector(".flt-value").value.trim();
      return { column, condition, value };
    })
    .filter((item) => item.column && item.value);
}

function addKvRow(container, initial = {}) {
  if (!container) {
    return;
  }
  const row = document.createElement("div");
  row.className = "kv-row";
  row.innerHTML = `
    <input type="text" class="kv-key" placeholder="field" value="${escapeHtml(initial.key || "")}" />
    <input type="text" class="kv-value" placeholder="value" value="${escapeHtml(initial.value || "")}" />
    <button class="icon-btn" type="button">×</button>
  `;
  row.querySelector(".icon-btn").addEventListener("click", () => row.remove());
  container.appendChild(row);
}

function readKvObject(container) {
  if (!container) {
    return {};
  }
  const result = {};
  Array.from(container.querySelectorAll(".kv-row")).forEach((row) => {
    const key = row.querySelector(".kv-key").value.trim();
    const valueRaw = row.querySelector(".kv-value").value;
    if (!key) {
      return;
    }
    result[key] = parseTypedValue(valueRaw);
  });
  return result;
}

function parseTypedValue(raw) {
  const value = String(raw ?? "").trim();
  if (value === "") {
    return "";
  }
  if (/^(true|false)$/i.test(value)) {
    return value.toLowerCase() === "true";
  }
  if (/^-?\d+$/.test(value)) {
    return Number.parseInt(value, 10);
  }
  if (/^-?\d+\.\d+$/.test(value)) {
    return Number.parseFloat(value);
  }
  return value;
}

function resetInsertGridByColumns() {
  state.insertColumns = String(el.insertColumns.value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

  if (!state.insertColumns.length) {
    state.insertColumns = ["name", "description", "is_active"];
    el.insertColumns.value = state.insertColumns.join(",");
  }

  state.insertRows = [blankInsertRow()];
  renderInsertGrid();
}

function blankInsertRow() {
  const row = {};
  state.insertColumns.forEach((column) => {
    row[column] = "";
  });
  return row;
}

function addInsertRow() {
  state.insertRows.push(blankInsertRow());
  renderInsertGrid();
}

function renderInsertGrid() {
  const table = el.insertGrid;
  table.innerHTML = "";

  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  state.insertColumns.forEach((column) => {
    const th = document.createElement("th");
    th.textContent = column;
    headRow.appendChild(th);
  });
  const removeTh = document.createElement("th");
  removeTh.textContent = "";
  headRow.appendChild(removeTh);
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  state.insertRows.forEach((rowData, rowIndex) => {
    const tr = document.createElement("tr");

    state.insertColumns.forEach((column) => {
      const td = document.createElement("td");
      const input = document.createElement("input");
      input.type = "text";
      input.value = rowData[column] ?? "";
      input.addEventListener("input", (event) => {
        state.insertRows[rowIndex][column] = event.target.value;
      });
      td.appendChild(input);
      tr.appendChild(td);
    });

    const tdRemove = document.createElement("td");
    const btn = document.createElement("button");
    btn.className = "icon-btn";
    btn.type = "button";
    btn.textContent = "×";
    btn.addEventListener("click", () => {
      state.insertRows.splice(rowIndex, 1);
      if (!state.insertRows.length) {
        state.insertRows.push(blankInsertRow());
      }
      renderInsertGrid();
    });
    tdRemove.appendChild(btn);
    tr.appendChild(tdRemove);

    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
}

function collectInsertRows() {
  return state.insertRows
    .map((row) => {
      const out = {};
      Object.entries(row).forEach(([key, value]) => {
        const clean = String(value ?? "").trim();
        if (clean !== "") {
          out[key] = parseTypedValue(clean);
        }
      });
      return out;
    })
    .filter((row) => Object.keys(row).length > 0);
}

function renderDataTable(table, columns, rows, options = {}) {
  table.innerHTML = "";
  const safeColumns = columns.length ? columns : inferColumns(rows);
  if (!safeColumns.length) {
    table.innerHTML = "<tbody><tr><td>Нет данных</td></tr></tbody>";
    return;
  }

  const thead = document.createElement("thead");
  const hr = document.createElement("tr");
  safeColumns.forEach((column) => {
    const th = document.createElement("th");
    th.textContent = repairMojibakeString(String(column || ""));
    hr.appendChild(th);
  });
  thead.appendChild(hr);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  rows.forEach((row, rowIndex) => {
    const tr = document.createElement("tr");
    safeColumns.forEach((column) => {
      const td = document.createElement("td");
      const value = row?.[column];
      td.textContent = value === undefined || value === null ? "" : repairMojibakeString(String(value));
      tr.appendChild(td);
    });
    if (options.clickable) {
      tr.style.cursor = "pointer";
      tr.addEventListener("click", () => options.onRowClick?.(row, tr, rowIndex));
    }
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
}

function inferColumns(rows) {
  const columns = [];
  rows.forEach((row) => {
    Object.keys(row || {}).forEach((key) => {
      if (!columns.includes(key)) {
        columns.push(key);
      }
    });
  });
  return columns;
}

function markSelectedResultRow(table, targetRow) {
  table.querySelectorAll("tr.selected").forEach((row) => row.classList.remove("selected"));
  targetRow.classList.add("selected");
}

function resolveRowIdFromResultRow(row, rowIndex) {
  const fromUuid = String(row?.uuid || "").trim();
  if (fromUuid) {
    return fromUuid;
  }
  const fromMapped = String(state.searchRowIds?.[rowIndex] || "").trim();
  if (fromMapped) {
    return fromMapped;
  }
  return "";
}

function setSelectedRowId(rowId) {
  state.selectedRowId = String(rowId || "");
  el.updateRowId.value = state.selectedRowId;
  if (el.fileRowId) {
    el.fileRowId.value = state.selectedRowId;
  }
  if (el.deleteRowId) {
    el.deleteRowId.value = state.selectedRowId;
  }
  el.deleteHint.textContent = state.selectedRowId
    ? `Выбрана строка: ${state.selectedRowId}`
    : "Строка не выбрана (можно ввести row_id вручную)";
  if (el.fileHint) {
    el.fileHint.textContent = state.selectedRowId
      ? `Выбрана строка: ${state.selectedRowId}. Укажите колонку с файлом и запустите операцию.`
      : "Выберите строку в таблице Search/Select Fields или введите row_id вручную.";
  }
}

async function handleAutoCancelRun() {
  let jobId = String(state.autoRunJobId || "").trim();
  if (!jobId) {
    const payload = await apiRequest("/dicts/autotest/jobs/current");
    const job = payload?.job && typeof payload.job === "object" ? payload.job : null;
    jobId = String(job?.job_id || "").trim();
  }
  if (!jobId) {
    toast("Нет активного автотеста для остановки.", "error");
    return;
  }
  await apiRequest(`/dicts/autotest/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
  });
  if (el.autoRunStatus) {
    el.autoRunStatus.dataset.state = "running";
    el.autoRunStatus.textContent = "Останавливаем автотест...";
  }
  toast("Запрос на остановку отправлен.", "ok");
}

function tryAutoSelectSingleResultRow(rows) {
  if (!Array.isArray(rows) || rows.length !== 1) {
    return;
  }
  const onlyRow = rows[0];
  const rowId = resolveRowIdFromResultRow(onlyRow, 0);
  if (!rowId) {
    return;
  }
  setSelectedRowId(rowId);
  autofillUpdateFields(onlyRow);
  const firstTableRow = el.searchResults.querySelector("tbody tr");
  if (firstTableRow) {
    markSelectedResultRow(el.searchResults, firstTableRow);
  }
}

async function handleCreateDict() {
  try {
    const name = getRequiredDictName();
    const mode = (el.udCreateMode?.value || "preset").trim();
    const payload = { name };
    let seedRows = [];
    if (mode === "manual") {
      const columns = readCreateColumns();
      if (!columns.length) {
        throw new Error("Добавьте хотя бы одну колонку выше.");
      }
      payload.columns = columns;
      syncCreateSeedGrid();
      seedRows = collectCreateSeedRows();
    } else {
      const preset = el.udPreset.value.trim();
      if (preset) {
        payload.preset = preset;
      }
    }

    const createResponse = await apiRequest("/dicts/create", { method: "POST", body: payload });
    const mergedResponse = { create: createResponse };

    if (mode === "manual") {
      if (seedRows.length) {
        try {
          const insertResponse = await apiRequest("/dicts/insert", {
            method: "POST",
            body: { name, rows: seedRows },
          });
          mergedResponse.insert = insertResponse;
          mergedResponse.seed_rows_inserted = seedRows.length;
        } catch (insertError) {
          mergedResponse.insert_error = insertError.message;
          setJson(el.udLastResponse, mergedResponse);
          throw new Error(insertError.message);
        }
      }
    }

    setJson(el.udLastResponse, mergedResponse);
    toast(`Справочник создан: ${name}`, "ok");
  } catch (error) {
    toast(error.message, "error");
    throw error;
  }
}

async function handleRemoveDict() {
  try {
    const name = getRequiredDictName();
    const response = await apiRequest("/dicts/remove", { method: "POST", body: { name } });
    setJson(el.udLastResponse, response);
    toast(`Справочник удален: ${name}`, "ok");
  } catch (error) {
    toast(error.message, "error");
    throw error;
  }
}

async function handleMetainfo() {
  try {
    const name = getRequiredDictName();
    const response = await apiRequest("/dicts/metainfo", { method: "POST", body: { name } });
    setJson(el.udLastResponse, response);
    toast("Метаинформация загружена", "ok");
  } catch (error) {
    toast(error.message, "error");
    throw error;
  }
}

async function handleQueryFrame() {
  try {
    const name = getRequiredDictName();
    const response = await apiRequest("/dicts/query-frame", { method: "POST", body: { name } });
    setJson(el.udLastResponse, response);
    toast("Структура загружена", "ok");
  } catch (error) {
    toast(error.message, "error");
    throw error;
  }
}

async function handleQuery() {
  try {
    const name = getRequiredDictName();
    const response = await apiRequest("/dicts/query", { method: "POST", body: { name } });
    setJson(el.udLastResponse, response);
    toast("Query выполнен", "ok");
  } catch (error) {
    toast(error.message, "error");
    throw error;
  }
}

async function handleInsertRows() {
  try {
    const name = getRequiredDictName();
    const rows = collectInsertRows();
    if (!rows.length) {
      throw new Error("Добавьте хотя бы одну строку для вставки.");
    }
    const response = await apiRequest("/dicts/insert", {
      method: "POST",
      body: { name, rows },
    });
    setJson(el.udLastResponse, response);
    toast(`Вставлено строк: ${rows.length}`, "ok");
  } catch (error) {
    toast(error.message, "error");
    throw error;
  }
}

async function handleSearch() {
  try {
    const name = getRequiredDictName();
    const filters = readFilters(el.searchFilters);
    const response = await apiRequest("/dicts/search", {
      method: "POST",
      body: { name, filters },
    });
    setJson(el.udLastResponse, response);

    const rows = Array.isArray(response.rows) ? response.rows : [];
    const columns = Array.isArray(response.columns) ? response.columns : inferColumns(rows);
    const rowIds = Array.isArray(response.row_ids) ? response.row_ids : rows.map((row) => row?.uuid).filter(Boolean);
    state.searchRows = rows;
    state.searchColumns = columns;
    state.searchRowIds = rowIds;

    renderDataTable(el.searchResults, columns, rows, {
      clickable: true,
      onRowClick: (row, tr, rowIndex) => {
        markSelectedResultRow(el.searchResults, tr);
        setSelectedRowId(resolveRowIdFromResultRow(row, rowIndex));
        autofillUpdateFields(row);
      },
    });
    if (!rows.length) {
      setSelectedRowId("");
    }
    tryAutoSelectSingleResultRow(rows);

    el.searchSummary.textContent = `Найдено строк: ${response.found_count ?? rows.length}`;
    toast("Search выполнен", "ok");
  } catch (error) {
    toast(error.message, "error");
    throw error;
  }
}

async function handleSelectFields() {
  try {
    const name = getRequiredDictName();
    const filters = readFilters(el.searchFilters);
    const response = await apiRequest("/dicts/select-fields", {
      method: "POST",
      body: { name, filters: filters.length ? filters : undefined },
    });
    setJson(el.udLastResponse, response);

    const rows = Array.isArray(response.rows) ? response.rows : [];
    const columns = Array.isArray(response.columns) ? response.columns : inferColumns(rows);
    const rowIds = Array.isArray(response.row_ids) ? response.row_ids : rows.map((row) => row?.uuid).filter(Boolean);
    state.searchRows = rows;
    state.searchColumns = columns;
    state.searchRowIds = rowIds;

    renderDataTable(el.searchResults, columns, rows, {
      clickable: true,
      onRowClick: (row, tr, rowIndex) => {
        markSelectedResultRow(el.searchResults, tr);
        setSelectedRowId(resolveRowIdFromResultRow(row, rowIndex));
        autofillUpdateFields(row);
      },
    });
    if (!rows.length) {
      setSelectedRowId("");
    }
    tryAutoSelectSingleResultRow(rows);
    const note = rowIds.length
      ? ""
      : " | uuid не вернулся — для update/remove нажми Search или укажи row_id вручную.";
    el.searchSummary.textContent = `Select-fields: найдено ${response.found_count ?? rows.length}${note}`;
    toast("Select-fields выполнен", "ok");
  } catch (error) {
    toast(error.message, "error");
    throw error;
  }
}

function autofillUpdateFields(row) {
  el.updateFields.innerHTML = "";
  Object.entries(row || {})
    .filter(([key]) => key !== "uuid")
    .forEach(([key, value]) => addKvRow(el.updateFields, { key, value: String(value ?? "") }));
  if (!el.updateFields.children.length) {
    addKvRow(el.updateFields);
  }
}

async function handleUpdateRow() {
  try {
    const name = getRequiredDictName();
    const rowId = String(el.updateRowId.value || "").trim();
    if (!rowId) {
      throw new Error("Укажите row_id для обновления.");
    }
    const values = readKvObject(el.updateFields);
    if (!Object.keys(values).length) {
      throw new Error("Добавьте хотя бы одно поле для обновления.");
    }
    const response = await apiRequest("/dicts/update", {
      method: "POST",
      body: { name, row_id: rowId, values },
    });
    setJson(el.udLastResponse, response);
    toast("Строка обновлена", "ok");
  } catch (error) {
    toast(error.message, "error");
    throw error;
  }
}

function readFileOperationContext() {
  const name = getRequiredDictName();
  const rowId = String(el.fileRowId?.value || state.selectedRowId || "").trim();
  const column = String(el.fileColumn?.value || "").trim();
  const fileIndex = Number.parseInt(String(el.fileIndex?.value ?? "0").trim(), 10);

  if (!rowId) {
    throw new Error("Выберите строку в таблице Search/Select Fields или введите row_id вручную.");
  }
  if (!column) {
    throw new Error("Укажите колонку с файлом.");
  }
  if (!Number.isFinite(fileIndex) || fileIndex < 0) {
    throw new Error("Индекс файла должен быть целым числом >= 0.");
  }
  return { name, rowId, column, fileIndex };
}

async function handleFileUpload() {
  try {
    const { name, rowId, column } = readFileOperationContext();
    const file = el.fileUploadInput?.files?.[0] || null;
    if (!file) {
      throw new Error("Выберите файл для загрузки.");
    }

    const dataBase64 = await fileToBase64(file);
    const response = await apiRequest("/dicts/file/upload", {
      method: "POST",
      timeoutMs: 180000,
      body: {
        name,
        row_id: rowId,
        column,
        filename: file.name,
        data_base64: dataBase64,
      },
    });
    setJson(el.udLastResponse, response);
    if (el.fileHint) {
      el.fileHint.textContent = `Файл загружен: ${file.name} (${column}, row_id=${rowId}). Можно выбрать другой файл.`;
    }
    resetFileInputSelection();
    toast("Файл загружен в справочник", "ok");
  } catch (error) {
    const parsed = parseHttpErrorMessage(error);
    setJson(el.udLastResponse, {
      status: "error",
      operation: "upload_file",
      source: parsed.source,
      http_status: parsed.statusCode,
      message: truncateForUi(parsed.detail, 3500),
      raw_error_preview: truncateForUi(parsed.raw, 700),
    });
    resetFileInputSelection();
    toast(
      `Загрузка не выполнена${parsed.statusCode ? ` (HTTP ${parsed.statusCode})` : ""}. Подробности в блоке "Ответ последней операции".`,
      "error"
    );
    throw error;
  }
}

async function handleFileClear() {
  resetFileInputSelection();
  if (el.fileHint) {
    el.fileHint.textContent = state.selectedRowId
      ? `Выбрана строка: ${state.selectedRowId}. Укажите колонку с файлом и запустите операцию.`
      : "Выберите строку в таблице Search/Select Fields или введите row_id вручную.";
  }
  toast("Выбранный файл очищен", "ok");
}

async function handleUdLastResponseDownload() {
  const raw = String(el.udLastResponse?.textContent || "").trim();
  if (!raw) {
    throw new Error("Нет данных для скачивания.");
  }

  let jsonText = raw;
  try {
    jsonText = JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    // Keep the raw block content to preserve diagnostic payload as shown in UI.
  }

  const ts = new Date().toISOString().replace(/[:.]/g, "-");
  const blob = new Blob([jsonText], { type: "application/json;charset=utf-8" });
  downloadBlob(blob, `last_operation_${ts}.json`);
  toast("JSON последней операции скачан", "ok");
}

async function handleFileDownload() {
  try {
    const { name, rowId, column, fileIndex } = readFileOperationContext();
    const { blob, filename } = await apiBinaryRequest("/dicts/file/download", {
      method: "POST",
      timeoutMs: 180000,
      body: {
        name,
        row_id: rowId,
        column,
        file_index: fileIndex,
      },
    });
    downloadBlob(blob, filename || `${name}_${column}_${rowId}.bin`);
    if (el.fileHint) {
      el.fileHint.textContent = `Файл скачан из колонки ${column} (index=${fileIndex}).`;
    }
    toast("Файл успешно скачан", "ok");
  } catch (error) {
    toast(error.message, "error");
    throw error;
  }
}

async function handleDeleteRows() {
  try {
    const name = getRequiredDictName();
    const mode = el.deleteMode.value;
    const allowMany = el.deleteAllowMany.checked;
    const fallbackRowId = String(el.deleteRowId?.value || "").trim();
    let payload = { name, allow_many: allowMany };

    if (mode === "selected") {
      const selected = String(state.selectedRowId || "").trim() || fallbackRowId;
      if (!selected) {
        throw new Error("Выберите строку в таблице Search/Select Fields или введите row_id вручную.");
      }
      payload.row_ids = [selected];
    } else {
      const filters = readFilters(el.deleteFilters);
      if (!filters.length) {
        throw new Error("Добавьте хотя бы один фильтр для удаления.");
      }
      payload.filters = filters;
    }

    const response = await apiRequest("/dicts/remove-rows", {
      method: "POST",
      body: payload,
    });
    setJson(el.udLastResponse, response);
    if (mode === "selected") {
      setSelectedRowId("");
    }
    toast("Удаление выполнено", "ok");
  } catch (error) {
    toast(error.message, "error");
    throw error;
  }
}

async function handleRestList() {
  try {
    const response = await apiRequest("/dicts-rest/list");
    setJson(el.restResponse, response);
    toast("REST list загружен", "ok");
  } catch (error) {
    toast(error.message, "error");
    throw error;
  }
}

async function handleRestCreate() {
  try {
    const name = String(el.restDictName.value || "").trim();
    if (!name) {
      throw new Error("Введите название справочника REST.");
    }
    const payload = {
      name,
      columns: [
        { name: "name", type: 1, note: "text", not_null: true, mask: false, interpretation: 3 },
        { name: "description", type: 10, note: "text", not_null: false, mask: false, interpretation: 3 },
      ],
      visible: 0,
      type: 0,
    };
    const response = await apiRequest("/dicts-rest/create", { method: "POST", body: payload });
    setJson(el.restResponse, response);
    toast("REST create выполнен", "ok");
  } catch (error) {
    toast(error.message, "error");
    throw error;
  }
}

async function handleRestMeta() {
  try {
    const uid = requireRestUid();
    const response = await apiRequest(`/dicts-rest/meta/${encodeURIComponent(uid)}`);
    setJson(el.restResponse, response);
    toast("REST meta загружен", "ok");
  } catch (error) {
    toast(error.message, "error");
    throw error;
  }
}

async function handleRestRows() {
  try {
    const uid = requireRestUid();
    const response = await apiRequest(`/dicts-rest/rows/${encodeURIComponent(uid)}`);
    setJson(el.restResponse, response);
    toast("REST rows загружены", "ok");
  } catch (error) {
    toast(error.message, "error");
    throw error;
  }
}

async function handleRestDelete() {
  try {
    const uid = requireRestUid();
    const response = await apiRequest(`/dicts-rest/delete/${encodeURIComponent(uid)}`, { method: "DELETE" });
    setJson(el.restResponse, response);
    toast("REST dictionary удален", "ok");
  } catch (error) {
    toast(error.message, "error");
    throw error;
  }
}

async function handleRestInsertRow() {
  try {
    const uid = requireRestUid();
    const row = readKvObject(el.restInsertFields);
    if (!Object.keys(row).length) {
      throw new Error("Добавьте хотя бы одно поле для вставки REST строки.");
    }
    const response = await apiRequest(`/dicts-rest/rows/${encodeURIComponent(uid)}`, {
      method: "POST",
      body: [row],
    });
    setJson(el.restResponse, response);
    toast("REST insert выполнен", "ok");
  } catch (error) {
    toast(error.message, "error");
    throw error;
  }
}

async function handleRestUpdateRow() {
  try {
    const uid = requireRestUid();
    const rowId = String(el.restUpdateRowId.value || "").trim();
    if (!rowId) {
      throw new Error("Укажите row_id для REST update.");
    }
    const values = readKvObject(el.restUpdateFields);
    if (!Object.keys(values).length) {
      throw new Error("Добавьте хотя бы одно поле для REST update.");
    }
    const response = await apiRequest(`/dicts-rest/rows/${encodeURIComponent(uid)}/${encodeURIComponent(rowId)}`, {
      method: "PUT",
      body: values,
    });
    setJson(el.restResponse, response);
    toast("REST update выполнен", "ok");
  } catch (error) {
    toast(error.message, "error");
    throw error;
  }
}

function requireRestUid() {
  const uid = String(el.restTableUid.value || "").trim();
  if (!uid) {
    throw new Error("Укажите uid таблицы REST.");
  }
  return uid;
}

async function handleParagraphList() {
  try {
    const query = {
      limit: Number.parseInt(el.pgLimit.value, 10) || 50,
      offset: Number.parseInt(el.pgOffset.value, 10) || 0,
      search: String(el.pgSearch.value || "").trim(),
      files_filter: String(el.pgFilesFilter.value || "").trim(),
    };
    const rows = await apiRequest("/paragraph/results", { query });
    renderParagraphResults(Array.isArray(rows) ? rows : []);
    setJson(el.pgResponse, rows);
    toast(`Загружено документов: ${Array.isArray(rows) ? rows.length : 0}`, "ok");
  } catch (error) {
    toast(error.message, "error");
    throw error;
  }
}

function renderParagraphResults(rows) {
  const columns = [
    "id",
    "name",
    "date_write",
    "id_document",
    "files_status",
    "files_linked_count",
  ];
  renderDataTable(el.pgResultsTable, columns, rows, {
    clickable: true,
    onRowClick: (row, tr) => {
      markSelectedResultRow(el.pgResultsTable, tr);
      el.pgSelectedId.value = row.id || "";
    },
  });
}

async function handleParagraphDetail() {
  try {
    const id = requireParagraphId();
    const response = await apiRequest(`/paragraph/results/${encodeURIComponent(id)}`);
    setJson(el.pgResponse, response);
    toast("Detail загружен", "ok");
  } catch (error) {
    toast(error.message, "error");
    throw error;
  }
}

async function handleParagraphContent() {
  try {
    const id = requireParagraphId();
    const response = await apiRequest(`/paragraph/results/${encodeURIComponent(id)}/content`);
    setJson(el.pgResponse, response);
    toast("Content загружен", "ok");
  } catch (error) {
    toast(error.message, "error");
    throw error;
  }
}

function requireParagraphId() {
  const id = String(el.pgSelectedId.value || "").trim();
  if (!id) {
    throw new Error("Выберите id документа из таблицы.");
  }
  return id;
}

function openParagraphExport(format) {
  try {
    const id = requireParagraphId();
    const base = getApiBase();
    const targetQuery = state.targetId != null ? `&target_id=${encodeURIComponent(state.targetId)}` : "";
    // Dlya sebya: export idet cherez query-param `format`, inache backend otdaet 404 Not Found.
    window.open(
      `${base}/paragraph/results/${encodeURIComponent(id)}/export?format=${encodeURIComponent(format)}${targetQuery}`,
      "_blank",
    );
  } catch (error) {
    toast(error.message, "error");
    throw error;
  }
}

function openParagraphArchive() {
  try {
    const id = requireParagraphId();
    const base = getApiBase();
    const targetQuery = state.targetId != null ? `?target_id=${encodeURIComponent(state.targetId)}` : "";
    window.open(`${base}/paragraph/results/${encodeURIComponent(id)}/export-archive${targetQuery}`, "_blank");
  } catch (error) {
    toast(error.message, "error");
    throw error;
  }
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}





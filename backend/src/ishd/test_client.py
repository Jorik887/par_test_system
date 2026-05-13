import asyncio
import logging

from src.ishd.client import IshdClient

logging.basicConfig(level=logging.INFO)


async def main() -> None:
    # Dlya sebya: public shag po rabote s ISHD (main).
    client = IshdClient()
    try:
        await client.connect()
        print("Handshake OK")

        # --- MODULE LIST (явный запрос) ---
        resp = await client.request_module_list()
        ml = resp.module_list_response

        print("\n=== MODULE LIST ===")
        print(f"Всего рабочих мест: {len(ml.list)}")
        for machine in ml.list:
            print(
                f"- Машина: id='{machine.machine_id}', "
                f"name='{machine.machine_name}', online={machine.online}"
            )
            for m in machine.modules:
                print(
                    f"    * Модуль: id='{m.id}', alias='{m.alias_id}', "
                    f"version='{m.version}', online={m.online}, "
                    f"authorized={m.authorized}"
                )

    finally:
        await client.close()
        print("ISHD connection closed")


if __name__ == "__main__":
    asyncio.run(main())

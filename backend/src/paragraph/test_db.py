import asyncio
from sqlalchemy import text

from src.paragraph.db import AsyncSessionLocal


async def main() -> None:
    # Dlya sebya: shag Paragraph-sloya (main).
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("SELECT 1"))
        print("SELECT 1 ->", result.scalar_one())


if __name__ == "__main__":
    asyncio.run(main())

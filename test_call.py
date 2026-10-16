"""One-line smoke test: python test_call.py"""
import asyncio

from pydantic_ai import Agent

from backend.llm import model, run_logged


async def main():
    result = await run_logged(Agent(model()), "Reply with one short sentence: are you working?", "smoke_test")
    print(result.output)
    print(result.usage)


asyncio.run(main())

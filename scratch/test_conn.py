import asyncio
import aiohttp
import sys

async def test_url(url):
    print(f"Testing URL: {url}...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                print(f"  Status: {resp.status}")
                text = await resp.text()
                print(f"  Response (first 200 chars): {text[:200]}")
    except Exception as e:
        print(f"  Error: {type(e).__name__}: {e}")

async def main():
    urls = [
        "https://api.telegram.org/",
        "https://super-cloud-9af3.ruzkovmisa.workers.dev/",
        "https://httpbin.org/ip"
    ]
    for url in urls:
        await test_url(url)
        print("-" * 40)

if __name__ == "__main__":
    asyncio.run(main())

import asyncio
from client import SREEnv, SREAction

async def test():
    env = SREEnv(base_url='http://localhost:8000')
    await env.connect()
    print('Connected')
    obs = await env.reset()
    print('Alert:', obs)
    await env.close()

asyncio.run(test())
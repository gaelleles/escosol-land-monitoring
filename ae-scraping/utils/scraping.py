from httpx import AsyncClient
from bs4 import BeautifulSoup


async def get_soup_from_url(client: AsyncClient, url: str) -> BeautifulSoup:
    res = await client.get(url)
    soup = BeautifulSoup(res.text, "html.parser")

    return soup

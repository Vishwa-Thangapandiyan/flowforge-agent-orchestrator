"""The agent paired once (D39): `flowforge mcp` with no folder answers about every project, the one the agent works
in by default, any other by name, and lists them all."""

import json
import textwrap
from pathlib import Path

import pytest
from mcp import Client

from flowforge.agent import build_server
from flowforge.projects import Projects


def app_folder(root: Path, name: str, url: str) -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "app.py").write_text(textwrap.dedent(f"""\
        import httpx

        def go():
            return httpx.get("{url}")
    """))
    return folder


@pytest.fixture
def two(tmp_path):
    reg = Projects()
    shop = reg.add(app_folder(tmp_path, "shop", "https://api.shop.test/v1"))
    blog = reg.add(app_folder(tmp_path, "blog", "https://api.blog.test/v2"))
    return shop, blog


async def call(tool, args=None):
    async with Client(build_server(None, None)) as client:
        result = await client.call_tool(tool, args or {})
        assert not result.is_error, result.content
        return json.loads(result.content[0].text)


def deps(got):
    return {d["id"] for d in got["dependencies"]}


async def test_it_lists_every_project_and_marks_the_one_the_agent_works_in(two, monkeypatch):
    shop, blog = two
    monkeypatch.chdir(Path(blog.path))
    got = await call("list_projects")
    rows = {p["id"]: p for p in got["projects"]}
    assert set(rows) == {"shop", "blog"} and rows["blog"]["current"] is True and rows["shop"]["current"] is False


async def test_by_default_it_answers_about_the_project_the_agent_works_in(two, monkeypatch):
    shop, blog = two
    monkeypatch.chdir(Path(shop.path))
    assert "api-api-shop-test" in deps(await call("get_map"))
    monkeypatch.chdir(Path(blog.path))
    assert "api-api-blog-test" in deps(await call("get_map"))


async def test_any_project_by_id_or_name(two, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)   # in no project
    assert "api-api-blog-test" in deps(await call("get_map", {"project": "blog"}))
    Projects().rename("shop", "My Shop")
    assert "api-api-shop-test" in deps(await call("get_map", {"project": "my shop"}))


async def test_an_unknown_project_says_how_to_find_one(two):
    async with Client(build_server(None, None)) as client:
        result = await client.call_tool("get_map", {"project": "nope"})
    assert result.is_error and "list_projects" in result.content[0].text


async def test_every_tool_takes_a_project(two):
    async with Client(build_server(None, None)) as client:
        tools = (await client.list_tools()).tools
    for t in tools:
        if t.name != "list_projects":
            assert "project" in t.input_schema["properties"], t.name


async def test_started_for_one_folder_it_still_answers_about_it_by_default(two, monkeypatch, tmp_path):
    from flowforge.storage import Storage

    shop, _ = two
    monkeypatch.chdir(tmp_path)
    async with Client(build_server(Path(shop.path), Storage(tmp_path / "a.db"))) as client:
        got = json.loads((await client.call_tool("get_map", {})).content[0].text)
    assert "api-api-shop-test" in deps(got)

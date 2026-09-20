"""MCP server exposing the offline documentation index over stdio."""

from __future__ import annotations

from mcp.server import MCPServer

from .mcp_config import ServerConfig
from .mcp_manager import IndexManager
from .mcp_tools import tool_get_page, tool_list_pages, tool_search_docs

INSTRUCTIONS = (
    "本服务提供 Counter-Strike 2 Workshop Tools 官方文档（Valve Developer Community）"
    "的离线全文检索。先用 search_docs 按关键词定位页面，再用 get_page 精读；"
    "已知确切页面标题或 pageid 时可直接 get_page。数据在服务启动时于后台自动更新，"
    "无需手动触发。仅回答与该工具集文档相关的问题。"
)


def build_server(manager: IndexManager) -> MCPServer:
    mcp = MCPServer("cs2wt-docs", instructions=INSTRUCTIONS)

    @mcp.tool()
    def search_docs(query: str, limit: int = 10) -> str:
        """按关键词检索 Counter-Strike 2 Workshop Tools 官方文档的离线全文索引。

        何时使用：需要查找 CS2 Workshop Tools 文档中的术语、命令、概念、实体时；
        回答任何涉及该工具集用法的技术问题前，应先用本工具定位来源页面。
        何时不使用：已知道确切页面标题或 pageid 时，直接调用 get_page 更高效；
        与 CS2 Workshop Tools 文档无关的问题不要使用。
        返回：JSON，含 count 与 results（每项含 pageid、title、url、snippet、score；
        score 为 bm25，越小越相关）。索引初始化中或刷新失败时返回 status 字段；
        后台刷新进行中时额外带 refreshing 字段。
        """
        return tool_search_docs(manager, query, limit)

    @mcp.tool()
    def get_page(id_or_title: str, section: str | None = None) -> str:
        """读取某个文档页面的正文，可按章节只取一部分。

        何时使用：已知页面标题或 pageid，需要阅读其内容；或只想读取某章节以控制返回体积。
        何时不使用：只知道模糊关键词时，先用 search_docs 定位。
        参数：id_or_title 为纯数字时按 pageid 查询，否则按页面标题查询；
        section 为可选的章节标题（不区分大小写，支持部分匹配）。
        返回：JSON，含 found、pageid、title、url、revid、timestamp、content；
        未找到页面或章节时 found 为 false。索引初始化中或刷新失败时返回 status 字段；
        后台刷新进行中时额外带 refreshing 字段。
        """
        return tool_get_page(manager, id_or_title, section)

    @mcp.tool()
    def list_pages() -> str:
        """列出当前索引收录的全部文档页面。

        何时使用：需要了解文档覆盖范围、列举全部页面，或确认某主题是否被收录。
        何时不使用：已有明确查询词时，用 search_docs 更合适。
        返回：JSON，含 count 与 pages（每项含 pageid、title）。索引初始化中或刷新失败时返回
        status 字段；后台刷新进行中时额外带 refreshing 字段。
        """
        return tool_list_pages(manager)

    return mcp


def main(argv: list[str] | None = None) -> int:
    config = ServerConfig.from_sources(argv)
    manager = IndexManager(config)
    manager.start()
    try:
        build_server(manager).run()
    finally:
        manager.close()
    return 0
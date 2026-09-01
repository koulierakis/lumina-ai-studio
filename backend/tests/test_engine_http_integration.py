from code_builder.engine_http_integration import install_engine_http_routes
from code_builder.router import router as code_builder_router


def test_engine_http_route_is_installed_once_under_code_builder_prefix():
    install_engine_http_routes()
    install_engine_http_routes()
    matches = [
        route for route in code_builder_router.routes
        if getattr(route, "path", None) == "/api/code-builder/engines"
    ]
    assert len(matches) == 1
    assert "GET" in (getattr(matches[0], "methods", set()) or set())

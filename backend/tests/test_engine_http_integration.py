from code_builder.engine_http_integration import install_engine_http_routes
from code_builder.router import router as code_builder_router
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_engine_http_route_is_installed_once_under_code_builder_prefix():
    install_engine_http_routes()
    install_engine_http_routes()
    app = FastAPI()
    app.include_router(code_builder_router)
    response = TestClient(app).get("/api/code-builder/engines")
    assert response.status_code == 200
    assert "/api/code-builder/engines" in app.openapi()["paths"]
    assert set(app.openapi()["paths"]["/api/code-builder/engines"]) == {"get"}

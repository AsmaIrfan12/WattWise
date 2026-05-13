from app.routers.notifications import mark_read

def test_mark_read_function_exists_and_is_callable():
    """Smoke-test: the handler is importable and callable (async)."""
    import asyncio
    assert callable(mark_read)

def test_notifications_router_has_post_read_route():
    """Verify the router registers a POST route for /{id}/read."""
    from app.routers.notifications import router
    post_paths = [
        r.path for r in router.routes
        if hasattr(r, 'methods') and 'POST' in r.methods
    ]
    assert any('/read' in p for p in post_paths), (
        f"No POST .../read route found. Registered POST paths: {post_paths}"
    )

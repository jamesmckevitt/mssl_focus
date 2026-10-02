from .metadata import APP_AUTHOR, APP_EMAIL, APP_INSTITUTION, APP_VERSION


def __getattr__(name):
    # Imported on demand: the application modules need Tk, and ``main`` needs
    # the private licence module, neither of which the pure helpers require.
    if name == "ImageComparer":
        from .app import ImageComparer
        return ImageComparer
    if name == "run_app":
        from .main import run_app
        return run_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "APP_AUTHOR",
    "APP_EMAIL",
    "APP_INSTITUTION",
    "APP_VERSION",
    "ImageComparer",
    "run_app",
]

"""Entry point for state inspection; also avoids shadowing Python's inspect module."""

if __name__ == "inspect":
    import os
    import sysconfig

    _stdlib_file = os.path.join(sysconfig.get_path("stdlib"), "inspect.py")
    with open(_stdlib_file, "rb") as _handle:
        exec(compile(_handle.read(), _stdlib_file, "exec"), globals())
else:
    from ops_sim.inspect_tool import main

    if __name__ == "__main__":
        raise SystemExit(main())

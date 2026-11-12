"""Frozen entry point; divert the owned translation child before importing Qt."""
import sys

if __name__ == "__main__":
    if sys.argv[1:2] == ["--translation-worker"]:
        from global_pulse.translation_worker import main
        raise SystemExit(main(sys.argv[2:]))
    from global_pulse.__main__ import main
    raise SystemExit(main())

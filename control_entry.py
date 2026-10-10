"""Desktop entry point; MCP entry points remain independent of the UI shell."""
import sys
import codex_hybrid_control as core


def main():
    if not any(flag in sys.argv for flag in ('--mcp-computer','--mcp-workers','--supervise-worker',
                                            '--bridge-child-computer','--bridge-child-worker','--accessibility-child')):
        from hybrid_runtime import enable_gui_log
        enable_gui_log()
        from hybrid_ui import install
        install(core)
    core.main_with_watchdog()


if __name__=='__main__':
    try:
        main()
    except BaseException as error:
        core._fatal_startup_error(error)
        raise SystemExit(1)

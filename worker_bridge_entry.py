import codex_hybrid_control as core
import sys

if __name__ == "__main__":
    if '--api-guard' in sys.argv:
        from hybrid_api_guard import main
        main()
        raise SystemExit(0)
    if '--hybrid-stop-guard' in sys.argv:
        from hybrid_stop_guard import main
        main()
        raise SystemExit(0)
    if '--supervise-worker' in sys.argv:
        from hybrid_process import supervisor_main
        raise SystemExit(supervisor_main())
    if '--bridge-child-worker' in sys.argv:
        from hybrid_bridge_host import announce_transport
        announce_transport()
        core.run_worker_mcp_server()
    else:
        from hybrid_bridge_host import run_host
        run_host(core, 'worker')

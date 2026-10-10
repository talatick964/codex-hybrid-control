import sys
import codex_hybrid_control as core

if __name__ == "__main__":
    if '--bridge-child-computer' in sys.argv:
        from hybrid_bridge_host import announce_transport
        announce_transport()
        core.run_computer_mcp_server()
    else:
        from hybrid_bridge_host import run_host
        run_host(core, 'computer')

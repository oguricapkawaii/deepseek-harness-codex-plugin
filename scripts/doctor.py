"""Check the local Harness, settings, and history without making a model request."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from deepseek_coding_agent.harness import HarnessLayout, _run_capture, model_override
from deepseek_coding_agent.history import list_history
async def main():
    layout = HarnessLayout.from_env()
    layout.validate()
    with model_override(layout, 'deepseek-v4-flash') as (_, _, patch):
        code, out, err = await _run_capture(layout.node_command(str(layout.cli), '--profile', 'headless', '--patch', str(patch), '--help'), layout.data_home, layout.runtime_env(), 30)
        if code:
            raise RuntimeError(err or out)
    history = await list_history(100)
    print('Harness installation:', layout.install_home)
    print('Isolated data:', layout.data_home)
    print('Headless launch and temporary model settings: OK')
    print('Readable sessions:', len(history['sessions']))
    print('No model request made.')
if __name__ == '__main__':
    asyncio.run(main())

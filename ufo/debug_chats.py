import asyncio
from ufo.automation.factory import get_desktop_automation
from ufo.automator.app_apis.telegram import TelegramGUIController

async def test():
    desktop = get_desktop_automation('Telegram.exe')
    c = TelegramGUIController(desktop)
    conn = await c.connect()
    print('Connect:', conn)
    
    # Dismiss any search overlay
    await c._dismiss_overlays()
    print('Dismissed overlays')
    
    # Re-find chat list
    c._chat_list = await c._find_chat_list()
    print('Chat list after dismiss:', c._chat_list)
    
    # Check if chat items exist
    items_exist = await c._chat_items_exist()
    print('Chat items exist:', items_exist)
    
    # Debug the walk directly
    if c._chat_list:
        def _do_walk():
            list_spec = c._chat_list.handle
            items = list_spec.children(control_type='ListItem')
            print('Number of ListItem children:', len(items))
            for i, item in enumerate(items[:10]):
                try:
                    text = (item.window_text() or '').strip()
                    print(f'  Item {i}: text="{text}"')
                    if text:
                        chat_name = text.split(',')[0].strip()
                        print(f'    -> chat_name: "{chat_name}"')
                except Exception as e:
                    print(f'  Item {i}: error {e}')
            return items
        
        import asyncio as aio
        items = await aio.to_thread(_do_walk)
        print('Total items:', len(items))

asyncio.run(test())
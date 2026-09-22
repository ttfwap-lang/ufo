import pywinauto
from pywinauto import Application
import time

app = Application(backend='uia').connect(process=33784)
win = app.top_window()

def find_by_class(element, target_class, max_depth=6, current_depth=0):
    if current_depth > max_depth:
        return None
    try:
        if target_class in element.class_name():
            return element
    except:
        pass
    try:
        for child in element.children():
            result = find_by_class(child, target_class, max_depth, current_depth + 1)
            if result:
                return result
    except:
        pass
    return None

# Find the chat list items and click more specifically
inner_widget = find_by_class(win, 'Dialogs::InnerWidget')
if inner_widget:
    print(f"Found Dialogs::InnerWidget")
    chats = inner_widget.children()
    print(f"Number of chat items: {len(chats)}")
    
    if chats:
        first_chat = chats[0]
        print(f"First chat: {first_chat.class_name()} | {first_chat.element_info.control_type}")
        print(f"  name: {first_chat.window_text()[:100]}")
        
        # Try different click methods
        print("\nTrying click methods...")
        
        # Method 1: click_input on the chat item itself
        try:
            first_chat.click_input()
            print("  click_input() on chat item - success")
        except Exception as e:
            print(f"  click_input() on chat item - failed: {e}")
        
        time.sleep(1)
        
        # Check HistoryWidget again
        history = find_by_class(win, 'HistoryWidget')
        if history:
            descendants = history.descendants()
            print(f"\nHistoryWidget descendants after click: {len(descendants)}")
            for i, desc in enumerate(descendants[:30]):
                print(f"  {i}: {desc.class_name()} | {desc.element_info.control_type} | name={desc.window_text()[:100]}")

# If that didn't work, try clicking on a specific part of the chat item
print("\n=== Trying to click on chat item children ===")
if inner_widget:
    chats = inner_widget.children()
    if chats:
        first_chat = chats[0]
        for child in first_chat.children():
            print(f"Child: {child.class_name()} | {child.element_info.control_type} | name={child.window_text()[:80]}")
            try:
                child.click_input()
                print("  click_input() - success")
                time.sleep(1)
                break
            except Exception as e:
                print(f"  click_input() - failed: {e}")

# After clicking, check for message input area
print("\n=== Checking for message input area ===")
def find_all_by_control_type(element, target_types, max_depth=8, current_depth=0):
    if current_depth > max_depth:
        return
    try:
        if element.element_info.control_type in target_types:
            print(f'  {element.element_info.control_type}: {element.class_name()} | auto_id={element.element_info.automation_id} | name={element.window_text()[:100]}')
    except:
        pass
    try:
        for child in element.children():
            find_all_by_control_type(child, target_types, max_depth, current_depth + 1)
    except:
        pass

find_all_by_control_type(win, ['Edit', 'Document', 'Text'])
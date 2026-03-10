"""
Example script demonstrating how to use the KanbanClient
"""

from kanban_client import KanbanClient

def main():
    # Replace with your actual API key
    API_KEY = "your-bot-api-key-here"
    BASE_URL = "https://dashboard-api-xxx.vercel.app"  # Replace with your actual URL

    # Initialize the client
    client = KanbanClient(api_key=API_KEY, base_url=BASE_URL)

    # Check API health
    print("Health Check:")
    print(client.health_check())
    print("\n---\n")

    # Get board info and show lists
    print("Board Info:")
    board = client.get_board()
    print(f"Board Name: {board.get('name', 'N/A')}")
    print(f"Lists:")
    for lst in board.get('lists', []):
        print(f"  - {lst.get('title')} (ID: {lst.get('id')})")
    print("\n---\n")

    # Example: Create a new list
    print("Creating 'Review' list...")
    new_list = client.create_list("Review")
    print(f"Created: {new_list.get('title')} (ID: {new_list.get('id')})")
    print("\n---\n")

    # Example: Create cards in the list
    print("Creating tasks:")
    card1 = client.create_card(new_list.get('id'), "Code review needed")
    print(f"  - {card1.get('title')} (Position: {card1.get('position')})")

    card2 = client.create_card(new_list.get('id'), "Merge pull requests")
    print(f"  - {card2.get('title')} (Position: {card2.get('position')})")
    print("\n---\n")

    # Example: Get and display labels
    print("Existing Labels:")
    labels = client.get_labels()
    for label in labels:
        print(f"  - {label.get('name')} ({label.get('color')})")
    print("\n---\n")

    # Example: Create a label
    print("Creating 'High Priority' label...")
    priority_label = client.create_label("High Priority", "red")
    print(f"Created: {priority_label.get('name')}")
    print("\n---\n")

    # Example: Add a comment to a card
    print(f"Adding comment to '{card1.get('title')}':")
    comment = client.add_comment(card1.get('id'), "Please review when you have a chance!")
    print(f"Comment ID: {comment.get('id')}")
    print("\n---\n")

    # Example: Upload a background image
    print("Uploading background image (if file exists)...")
    try:
        client.upload_background('/path/to/your/image.jpg')
        print("Background uploaded successfully!")
    except Exception as e:
        print(f"Could not upload background: {e}")
    print("\n---\n")

    # Example: Get activity feed
    print("Recent Activity:")
    activity = client.get_activity()
    for item in activity[:3]:  # Show first 3 activities
        print(f"  - {item.get('action')} on {item.get('card_title', item.get('list_title'))}")
    print("\n---\n")

    # Example: Get users
    print("User List:")
    users = client.get_users()
    for user in users[:3]:
        print(f"  - {user.get('username')} ({user.get('display_name')})")
    print("\n---\n")

    # Example: Get bots
    print("Bot List:")
    bots = client.get_bots()
    for bot in bots[:3]:
        print(f"  - {bot.get('name')} (Active: {bot.get('is_active', 'N/A')})")
    print("\n---\n")

    # Example: Checklists demo
    print("Checklists:")
    print("Cards with checklists:")
    card_with_checklist = client.create_card(new_list.get('id'), "Task with checklist")
    print(f"  Created: {card_with_checklist.get('title')}")

    # Create checklist
    new_checklist = client.create_checklist(
        card_with_checklist.get('id'),
        "Complete project"
    )
    print(f"  Created checklist: {new_checklist.get('title')}")

    # Add checklist items
    item1 = client.create_checklist_item(new_checklist.get('id'), "Write code")
    item2 = client.create_checklist_item(new_checklist.get('id'), "Write tests")
    item3 = client.create_checklist_item(new_checklist.get('id'), "Deploy")
    print(f"  Added items: Write code, Write tests, Deploy")

    print("\n---\n")
    print("All operations completed successfully!")


if __name__ == "__main__":
    main()
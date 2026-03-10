"""
Kanban Board API Client

A Python client for interacting with the Kanban board API.
Based on BOT_API.md documentation.
"""

import requests
from typing import Optional, Dict, List, Any
import json


class KanbanClient:
    """Client for interacting with the Kanban Board API"""

    def __init__(self, api_key: str, base_url: str = "https://dashboard-api-pied.vercel.app"):
        """
        Initialize the Kanban client

        Args:
            api_key: The API key for authentication (Bearer token)
            base_url: The base URL of the API endpoint
        """
        self.api_key = api_key
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        })

    def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make a request to the API"""
        url = f"{self.base_url}{endpoint}"
        try:
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise KanbanAPIError(f"API request failed: {str(e)}") from e

    def health_check(self) -> Dict[str, Any]:
        """Check if the API is healthy"""
        return self._make_request('GET', '/api/health')

    # ===== BOARD OPERATIONS =====

    def get_board(self) -> Dict[str, Any]:
        """Get board with all lists, cards, labels, background settings"""
        return self._make_request('GET', '/api/board')

    def update_board(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update board settings"""
        return self._make_request('PATCH', '/api/board', json=data)

    def upload_background(self, file_path: str) -> Dict[str, Any]:
        """Upload background image (max 5MB)"""
        url = f"{self.base_url}/api/board/background"
        with open(file_path, 'rb') as f:
            files = {'file': f}
            response = self.session.post(url, files=files)
            response.raise_for_status()
            return response.json()

    # ===== LIST OPERATIONS =====

    def create_list(self, title: str) -> Dict[str, Any]:
        """Create a new list"""
        return self._make_request('POST', '/api/lists', json={'title': title})

    def get_list(self, list_id: str) -> Dict[str, Any]:
        """Get list details"""
        return self._make_request('GET', f'/api/lists/{list_id}')

    def update_list(self, list_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update list"""
        return self._make_request('PATCH', f'/api/lists/{list_id}', json=data)

    def delete_list(self, list_id: str) -> None:
        """Delete a list"""
        self._make_request('DELETE', f'/api/lists/{list_id}')

    def copy_list(self, list_id: str) -> Dict[str, Any]:
        """Copy a list"""
        return self._make_request('POST', f'/api/lists/{list_id}/copy')

    def reorder_lists(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Reorder lists"""
        return self._make_request('PATCH', '/api/lists/reorder', json={'items': items})

    def add_list_member(self, list_id: str, username: str) -> Dict[str, Any]:
        """Add member to list"""
        return self._make_request('POST', f'/api/lists/{list_id}/members', json={'username': username})

    def remove_list_member(self, list_id: str, username: str) -> None:
        """Remove member from list"""
        self._make_request('DELETE', f'/api/lists/{list_id}/members/{username}')

    # ===== CARD OPERATIONS =====

    def get_card(self, card_id: str) -> Dict[str, Any]:
        """Get card details"""
        return self._make_request('GET', f'/api/cards/{card_id}')

    def create_card(self, list_id: str, title: str, position: Optional[int] = None) -> Dict[str, Any]:
        """Create a new card"""
        data = {'list_id': list_id, 'title': title}
        if position is not None:
            data['position'] = position
        return self._make_request('POST', '/api/cards', json=data)

    def update_card(self, card_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update card"""
        return self._make_request('PATCH', f'/api/cards/{card_id}', json=data)

    def delete_card(self, card_id: str) -> None:
        """Delete a card"""
        self._make_request('DELETE', f'/api/cards/{card_id}')

    def copy_card(self, card_id: str, list_id: Optional[str] = None) -> Dict[str, Any]:
        """Copy a card"""
        data = {'list_id': list_id} if list_id else {}
        return self._make_request('POST', f'/api/cards/{card_id}/copy', json=data)

    def move_card(self, card_id: str, list_id: str, position: int) -> Dict[str, Any]:
        """Move card to list at position"""
        return self._make_request('POST', f'/api/cards/{card_id}/move', json={
            'list_id': list_id,
            'position': position
        })

    def reorder_cards(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Reorder/move multiple cards"""
        return self._make_request('PATCH', '/api/cards/reorder', json={'items': items})

    def get_templates_list(self) -> List[Dict[str, Any]]:
        """List template cards"""
        return self._make_request('GET', '/api/cards/templates/list')['data'] or []

    # ===== LABEL OPERATIONS =====

    def get_labels(self) -> List[Dict[str, Any]]:
        """List all labels"""
        return self._make_request('GET', '/api/labels')

    def create_label(self, name: str, color: str) -> Dict[str, Any]:
        """Create a label"""
        return self._make_request('POST', '/api/labels', json={'name': name, 'color': color})

    def update_label(self, label_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update label"""
        return self._make_request('PATCH', f'/api/labels/{label_id}', json=data)

    def delete_label(self, label_id: str) -> None:
        """Delete a label"""
        self._make_request('DELETE', f'/api/labels/{label_id}')

    def toggle_label_on_card(self, card_id: str, label_id: str) -> Dict[str, Any]:
        """Toggle label on card"""
        return self._make_request('POST', f'/api/cards/{card_id}/labels', json={'label_id': label_id})

    # ===== CHECKLIST OPERATIONS =====

    def get_checklists(self, card_id: str) -> List[Dict[str, Any]]:
        """Get checklists (tree structure)"""
        return self._make_request('GET', f'/api/cards/{card_id}/checklists')

    def create_checklist(self, card_id: str, title: str) -> Dict[str, Any]:
        """Create a checklist"""
        return self._make_request('POST', f'/api/cards/{card_id}/checklists', json={'title': title})

    def update_checklist(self, checklist_id: str, title: str) -> Dict[str, Any]:
        """Update checklist title"""
        return self._make_request('PATCH', f'/api/checklists/{checklist_id}', json={'title': title})

    def delete_checklist(self, checklist_id: str) -> None:
        """Delete a checklist"""
        self._make_request('DELETE', f'/api/checklists/{checklist_id}')

    def create_checklist_item(self, checklist_id: str, title: str, parent_id: Optional[str] = None) -> Dict[str, Any]:
        """Create a checklist item"""
        data = {'title': title}
        if parent_id:
            data['parent_id'] = parent_id
        return self._make_request('POST', f'/api/checklists/{checklist_id}/items', json=data)

    def update_checklist_item(self, checklist_item_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update checklist item"""
        return self._make_request('PATCH', f'/api/checklist-items/{checklist_item_id}', json=data)

    def delete_checklist_item(self, checklist_item_id: str) -> None:
        """Delete a checklist item"""
        self._make_request('DELETE', f'/api/checklist-items/{checklist_item_id}')

    # ===== COMMENT OPERATIONS =====

    def add_comment(self, card_id: str, body: str) -> Dict[str, Any]:
        """Add comment to card"""
        return self._make_request('POST', f'/api/cards/{card_id}/comments', json={'body': body})

    def update_comment(self, comment_id: str, body: str) -> Dict[str, Any]:
        """Edit comment"""
        return self._make_request('PATCH', f'/api/comments/{comment_id}', json={'body': body})

    def delete_comment(self, comment_id: str) -> None:
        """Delete comment"""
        self._make_request('DELETE', f'/api/comments/{comment_id}')

    def toggle_reaction(self, comment_id: str, emoji: str) -> Dict[str, Any]:
        """Toggle emoji reaction"""
        return self._make_request('POST', f'/api/comments/{comment_id}/reactions', json={'emoji': emoji})

    # ===== ATTACHMENT OPERATIONS =====

    def upload_attachment(self, card_id: str, file_path: str) -> Dict[str, Any]:
        """Upload attachment to card (max 10MB)"""
        url = f"{self.base_url}/api/cards/{card_id}/attachments"
        with open(file_path, 'rb') as f:
            files = {'file': f}
            response = self.session.post(url, files=files)
            response.raise_for_status()
            return response.json()

    def delete_attachment(self, attachment_id: str) -> None:
        """Delete attachment"""
        self._make_request('DELETE', f'/api/attachments/{attachment_id}')

    # ===== CUSTOM FIELDS OPERATIONS =====

    def get_custom_fields(self) -> List[Dict[str, Any]]:
        """List custom field definitions"""
        return self._make_request('GET', '/api/custom-fields')

    def create_custom_field(self, name: str, field_type: str, options: Optional[List[str]] = None) -> Dict[str, Any]:
        """Create custom field"""
        data = {'name': name, 'type': field_type}
        if options:
            data['options'] = options
        return self._make_request('POST', '/api/custom-fields', json=data)

    def update_custom_field(self, field_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update custom field"""
        return self._make_request('PATCH', f'/api/custom-fields/{field_id}', json=data)

    def delete_custom_field(self, field_id: str) -> None:
        """Delete custom field"""
        self._make_request('DELETE', f'/api/custom-fields/{field_id}')

    def set_custom_field_value(self, card_id: str, field_id: str, value: str) -> Dict[str, Any]:
        """Set custom field value on card"""
        return self._make_request('PUT',
                                 f'/api/custom-fields/cards/{card_id}/custom-fields/{field_id}',
                                 json={'value': value})

    # ===== ACTIVITY OPERATIONS =====

    def get_activity(self) -> List[Dict[str, Any]]:
        """Get board activity feed"""
        return self._make_request('GET', '/api/activity')

    def get_card_activity(self, card_id: str) -> List[Dict[str, Any]]:
        """Get activity for a specific card"""
        return self._make_request('GET', f'/api/activity/cards/{card_id}/activity')

    # ===== USER OPERATIONS =====

    def get_users(self) -> List[Dict[str, Any]]:
        """List all users"""
        return self._make_request('GET', '/api/users')

    def create_user(self, username: str, display_name: str,
                    avatar: Optional[str] = None, color: Optional[str] = None) -> Dict[str, Any]:
        """Create a user"""
        data = {'username': username, 'display_name': display_name}
        if avatar:
            data['avatar'] = avatar
        if color:
            data['color'] = color
        return self._make_request('POST', '/api/users', json=data)

    def update_user(self, username: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update user"""
        return self._make_request('PATCH', f'/api/users/{username}', json=data)

    def delete_user(self, username: str) -> None:
        """Delete a user"""
        self._make_request('DELETE', f'/api/users/{username}')

    # ===== BOT OPERATIONS =====

    def get_bots(self) -> List[Dict[str, Any]]:
        """List all bots"""
        return self._make_request('GET', '/api/bots')

    def create_bot(self, name: str, description: Optional[str] = None) -> Dict[str, Any]:
        """Create a bot (returns api_key)"""
        data = {'name': name}
        if description:
            data['description'] = description
        return self._make_request('POST', '/api/bots', json=data)

    def get_bot(self, bot_id: str) -> Dict[str, Any]:
        """Get bot details"""
        return self._make_request('GET', f'/api/bots/{bot_id}')

    def update_bot(self, bot_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update bot"""
        return self._make_request('PATCH', f'/api/bots/{bot_id}', json=data)

    def delete_bot(self, bot_id: str) -> None:
        """Delete a bot"""
        self._make_request('DELETE', f'/api/bots/{bot_id}')

    def regenerate_bot_key(self, bot_id: str) -> Dict[str, Any]:
        """Regenerate API key"""
        return self._make_request('POST', f'/api/bots/{bot_id}/regenerate-key')

    # ===== WATCHER OPERATIONS =====

    def toggle_watcher(self, card_id: str) -> Dict[str, Any]:
        """Toggle current user as watcher on card"""
        return self._make_request('POST', f'/api/cards/{card_id}/watchers')


class KanbanAPIError(Exception):
    """Custom exception for Kanban API errors"""
    pass


# ===== EXAMPLE USAGE =====

def example_usage(api_key: str):
    """Example usage of the KanbanClient"""

    # Initialize the client
    client = KanbanClient(api_key)

    # Health check
    print("Health Check:")
    print(client.health_check())
    print()

    # Get board info
    print("Getting Board Info:")
    board = client.get_board()
    print(json.dumps(board.get('name'), indent=2))
    print()

    # Create a new list
    print("Creating a new list:")
    new_list = client.create_list("To Do")
    print(f"Created list: {new_list.get('id')} - {new_list.get('title')}")
    print()

    # Get list ID for next operations
    my_list_id = new_list.get('id')

    # Create cards
    print("Creating sample cards:")
    card1 = client.create_card(my_list_id, "Review pull requests")
    card2 = client.create_card(my_list_id, "Update documentation")
    print(f"Created cards: {card1.get('title')}, {card2.get('title')}")
    print()

    # Get labels
    print("Getting labels:")
    labels = client.get_labels()
    print(json.dumps(labels, indent=2)[:500] + "...")
    print()

    # Create a label
    print("Creating a new label:")
    new_label = client.create_label("Bug", "red")
    print(f"Created label: {new_label.get('name')} with color {new_label.get('color')}")
    print()

    # Add comment to card
    print("Adding comment to card:")
    comment = client.add_comment(card1.get('id'), "Please review this ASAP")
    print(f"Comment added: {comment.get('id')}")
    print()

    # Upload background
    print("Uploading background image:")
    try:
        background = client.upload_background('background.jpg')
        print(f"Background uploaded: {background.get('url')}")
    except Exception as e:
        print(f"Could not upload background: {str(e)}")
    print()

    # Get activity feed
    print("Getting activity feed:")
    activity = client.get_activity()
    print(f"Found {len(activity)} activity items")
    print()

    # User operations
    print("Getting users:")
    users = client.get_users()
    for user in users[:3]:  # Show first 3 users
        print(f"- {user.get('username')}: {user.get('display_name')}")
    print()

    # Bot operations
    print("Getting bots:")
    bots = client.get_bots()
    for bot in bots[:3]:  # Show first 3 bots
        print(f"- {bot.get('name')}")
    print()


if __name__ == "__main__":
    # To use this script, replace with your actual API key
    # You can also modify the base_url to match your deployment
    EXAMPLE_API_KEY = "your-api-key-here"
    example_usage(EXAMPLE_API_KEY)
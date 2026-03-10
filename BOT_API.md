# Dashboard Bot API Reference

## Authentication

All requests require the `Authorization` header:

```
Authorization: Bearer <bot_api_key>
```

The bot's username is used automatically for activity logging. You can also set `X-User` header to attribute actions to a specific user.

**Base URL:** `https://dashboard-api-xxx.vercel.app` (your API deployment URL)

---

## Board

| Method | Endpoint | Body | Description |
|--------|----------|------|-------------|
| GET | `/api/board` | — | Get board with all lists, cards, labels, background settings |
| PATCH | `/api/board` | `{ name?, background_color?, background_image? }` | Update board |
| POST | `/api/board/background` | `multipart/form-data` with `file` | Upload background image (max 5MB) |

---

## Lists

| Method | Endpoint | Body | Description |
|--------|----------|------|-------------|
| POST | `/api/lists` | `{ title }` | Create list |
| PATCH | `/api/lists/:id` | `{ title?, position?, is_archived? }` | Update list |
| DELETE | `/api/lists/:id` | — | Delete list |
| POST | `/api/lists/:id/copy` | — | Copy list |
| POST | `/api/lists/:id/sort` | `{ by }` | Sort list cards |
| PATCH | `/api/lists/reorder` | `{ items: [{ id, position }] }` | Reorder lists |
| POST | `/api/lists/:id/members` | `{ username }` | Add member to list |
| DELETE | `/api/lists/:id/members/:username` | — | Remove member from list |

---

## Cards

| Method | Endpoint | Body | Description |
|--------|----------|------|-------------|
| GET | `/api/cards/:id` | — | Get card detail (checklists, comments, attachments, etc.) |
| POST | `/api/cards` | `{ list_id, title, position? }` | Create card |
| PATCH | `/api/cards/:id` | `{ title?, description?, due_date?, start_date?, due_complete?, cover_color?, cover_image?, is_archived?, is_template?, list_id?, position? }` | Update card |
| DELETE | `/api/cards/:id` | — | Delete card |
| POST | `/api/cards/:id/copy` | `{ list_id? }` | Copy card (optionally to another list) |
| POST | `/api/cards/:id/move` | `{ list_id, position }` | Move card to list at position |
| PATCH | `/api/cards/reorder` | `{ items: [{ id, list_id, position }] }` | Reorder/move multiple cards |
| GET | `/api/cards/templates/list` | — | List template cards |

---

## Labels

| Method | Endpoint | Body | Description |
|--------|----------|------|-------------|
| GET | `/api/labels` | — | List all labels |
| POST | `/api/labels` | `{ name, color }` | Create label |
| PATCH | `/api/labels/:id` | `{ name?, color? }` | Update label |
| DELETE | `/api/labels/:id` | — | Delete label |
| POST | `/api/cards/:cardId/labels` | `{ label_id }` | Toggle label on card |

---

## Checklists

| Method | Endpoint | Body | Description |
|--------|----------|------|-------------|
| GET | `/api/cards/:cardId/checklists` | — | Get checklists (tree structure with nested children) |
| POST | `/api/cards/:cardId/checklists` | `{ title }` | Create checklist |
| PATCH | `/api/checklists/:id` | `{ title }` | Update checklist title |
| DELETE | `/api/checklists/:id` | — | Delete checklist |
| POST | `/api/checklists/:id/items` | `{ title, parent_id? }` | Create item (`parent_id` for sub-items) |
| PATCH | `/api/checklist-items/:id` | `{ title?, is_checked?, due_date? }` | Update checklist item |
| DELETE | `/api/checklist-items/:id` | — | Delete checklist item (cascades to sub-items) |

### Checklist Response Structure

Items are returned as a tree. Each item may have a `children` array:

```json
{
  "id": "...",
  "title": "Checklist",
  "items": [
    {
      "id": "item-1",
      "title": "Parent task",
      "is_checked": false,
      "parent_id": null,
      "children": [
        {
          "id": "item-2",
          "title": "Sub-task",
          "is_checked": false,
          "parent_id": "item-1",
          "children": []
        }
      ]
    }
  ]
}
```

---

## Comments

| Method | Endpoint | Body | Description |
|--------|----------|------|-------------|
| POST | `/api/cards/:cardId/comments` | `{ body }` | Add comment |
| PATCH | `/api/comments/:id` | `{ body }` | Edit comment |
| DELETE | `/api/comments/:id` | — | Delete comment |
| POST | `/api/comments/:id/reactions` | `{ emoji }` | Toggle emoji reaction |

---

## Attachments

| Method | Endpoint | Body | Description |
|--------|----------|------|-------------|
| POST | `/api/cards/:cardId/attachments` | `multipart/form-data` with `file` (max 10MB) | Upload attachment |
| DELETE | `/api/attachments/:id` | — | Delete attachment |

---

## Custom Fields

| Method | Endpoint | Body | Description |
|--------|----------|------|-------------|
| GET | `/api/custom-fields` | — | List custom field definitions |
| POST | `/api/custom-fields` | `{ name, type, options? }` | Create field (type: text/number/dropdown/checkbox/date) |
| PATCH | `/api/custom-fields/:id` | `{ name?, type?, options? }` | Update field |
| DELETE | `/api/custom-fields/:id` | — | Delete field |
| PUT | `/api/custom-fields/cards/:cardId/custom-fields/:fieldId` | `{ value }` | Set field value on card |

---

## Activity

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/activity` | Get board activity feed |
| GET | `/api/activity/cards/:cardId/activity` | Get activity for a specific card |

---

## Users

| Method | Endpoint | Body | Description |
|--------|----------|------|-------------|
| GET | `/api/users` | — | List all users |
| POST | `/api/users` | `{ username, displayName, avatar?, color? }` | Create user |
| PATCH | `/api/users/:username` | `{ displayName?, avatar?, color? }` | Update user |
| DELETE | `/api/users/:username` | — | Delete user |

---

## Bots

| Method | Endpoint | Body | Description |
|--------|----------|------|-------------|
| GET | `/api/bots` | — | List all bots |
| POST | `/api/bots` | `{ name, description? }` | Create bot (returns `api_key` once) |
| GET | `/api/bots/:id` | — | Get bot details |
| PATCH | `/api/bots/:id` | `{ name?, description?, is_active? }` | Update bot |
| DELETE | `/api/bots/:id` | — | Delete bot |
| POST | `/api/bots/:id/regenerate-key` | — | Regenerate API key (returns new `api_key`) |

---

## Watchers

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/cards/:cardId/watchers` | Toggle current user as watcher on card |

---

## Health Check

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Returns `{ status: "ok", timestamp: "..." }` |

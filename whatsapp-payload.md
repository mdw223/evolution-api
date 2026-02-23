These are **webhook/event types** from the [Evolution API](https://doc.evolution-api.com/v2/en/integrations/s3minio) — a WhatsApp API wrapper. Here's what each event means:

---

**Instance Lifecycle**

- `APPLICATION_STARTUP` — Fired when the Evolution API server starts up
- `LOGOUT_INSTANCE` — Fired when a WhatsApp instance logs out
- `REMOVE_INSTANCE` — Fired when an instance is deleted/removed from the server
- `QRCODE_UPDATED` — Fired when a new QR code is generated (for pairing WhatsApp)
- `CONNECTION_UPDATE` — Fired when the connection state changes (connecting, open, closed, etc.)

---

**Messages**

- `MESSAGES_SET` — Initial bulk load of messages when the instance first connects/syncs
- `MESSAGES_UPSERT` — A new message was received or sent (insert or update)
- `MESSAGES_UPDATE` — An existing message was updated (e.g. read receipt, delivery status)
- `MESSAGES_DELETE` — A message was deleted
- `SEND_MESSAGE` — Fired when a message is sent through the API

---

**Chats**

- `CHATS_SET` — Initial bulk load of chats on connection/sync
- `CHATS_UPSERT` — A chat was created or updated
- `CHATS_UPDATE` — Metadata on a chat changed (e.g. mute, pin, archive)
- `CHATS_DELETE` — A chat was deleted

---

**Contacts**

- `CONTACTS_SET` — Initial bulk load of contacts on sync
- `CONTACTS_UPSERT` — A contact was added or updated
- `CONTACTS_UPDATE` — A contact's info was updated (name, profile photo, etc.)

---

**Groups**

- `GROUPS_UPSERT` — A group was created or its metadata was updated
- `GROUP_UPDATE` — Group settings changed (subject, description, etc.)
- `GROUP_PARTICIPANTS_UPDATE` — A participant was added, removed, promoted, or demoted in a group

---

**Presence**

- `PRESENCE_UPDATE` — A contact's presence changed (online, offline, typing, recording audio)

---

**Labels** _(WhatsApp Business)_

- `LABELS_EDIT` — A label was created, edited, or deleted
- `LABELS_ASSOCIATION` — A label was associated or dissociated from a chat/message

---

**Typebot Integration**

- `TYPEBOT_START` — A Typebot flow was triggered/started for a contact
- `TYPEBOT_CHANGE_STATUS` — The status of an active Typebot session changed (e.g. paused, finished)

---

**In the context of S3/MinIO**, these events determine _which events trigger file storage_ — for example, storing received media (`MESSAGES_UPSERT`) or chat history to your S3/MinIO bucket. You typically configure which of these events you want to subscribe to in your webhook or integration settings.

Based on your JSON, the `messageType` field tells you what kind of message was sent. Here are the main types you'll encounter in WhatsApp:

---

## Message Types & Their Paths

### 1. `imageMessage` — Image only OR image with caption

- The one in your data. Caption is **optional**, so if someone sends just an image with no text, `caption` will be absent/null.
- Image URL → `body.data.message.imageMessage.url`
- Caption → `body.data.message.imageMessage.caption` _(may not exist)_

### 2. `conversation` — Plain text message only

- Just a text message, no media attached.
- Message text → `body.data.message.conversation`

### 3. `extendedTextMessage` — Text with a link preview

- When someone sends a URL and WhatsApp generates a preview card.
- Message text → `body.data.message.extendedTextMessage.text`

### 4. `videoMessage` — Video only OR video with caption

- Caption → `body.data.message.videoMessage.caption` _(may not exist)_
- URL → `body.data.message.videoMessage.url`

### 5. `documentMessage` — A file/document (PDF, Word, etc.)

- Caption → `body.data.message.documentMessage.caption`
- File name → `body.data.message.documentMessage.fileName`

### 6. `audioMessage` — Voice note or audio file

- URL → `body.data.message.audioMessage.url`

### 7. `stickerMessage` — A sticker

- URL → `body.data.message.stickerMessage.url`

---

## How to Handle This in n8n

Since you want both plain text messages AND image+caption messages, the tricky part is that the text lives in **different paths** depending on the type. The cleanest way to handle this is with a **Switch node** after your group filter:

**Switch node** on `{{$json.body.data.messageType}}`:

- **Case 1:** `imageMessage` → Set node pulling `imageMessage.url` + `imageMessage.caption`
- **Case 2:** `conversation` → Set node pulling `message.conversation` as the text, image URL = blank
- **Case 3:** `extendedTextMessage` → Set node pulling `extendedTextMessage.text`, image URL = blank

All three branches then feed into the same **Google Sheets** node, so every row has consistent columns like `sender_name`, `message_text`, `image_url`, and `timestamp` — just with some fields blank depending on the type.

Now I have a clear picture of the JSON. Let me break this down for you clearly.

---

## Understanding Your WhatsApp Webhook JSON

Here's a map of the key variables in your payload:

| Variable Path                            | Value in Your Data             | What It Means                                                                    |
| ---------------------------------------- | ------------------------------ | -------------------------------------------------------------------------------- |
| `body.event`                             | `"messages.upsert"`            | The type of event (new message)                                                  |
| `body.data.key.remoteJid`                | `"120363367748965795@g.us"`    | **The Group ID** — ends in `@g.us` for groups, `@s.whatsapp.net` for individuals |
| `body.data.key.fromMe`                   | `false`                        | Whether YOU sent it (false = received)                                           |
| `body.data.key.participant`              | `"152428523561153@lid"`        | The sender's internal WhatsApp ID                                                |
| `body.data.key.participantAlt`           | `"19842398534@s.whatsapp.net"` | The sender's phone number                                                        |
| `body.data.pushName`                     | `"Ahmad Herzallah"`            | The sender's display name                                                        |
| `body.data.message.imageMessage.url`     | `https://mmg.whatsapp.net/...` | **The image URL**                                                                |
| `body.data.message.imageMessage.caption` | `"Join us tonight..."`         | **The message/caption on the image**                                             |
| `body.data.messageType`                  | `"imageMessage"`               | Type of message (`imageMessage`, `conversation`, etc.)                           |
| `body.data.messageTimestamp`             | `1771620830`                   | Unix timestamp of message                                                        |
| `body.sender`                            | `"17633130935@s.whatsapp.net"` | Alternate sender field                                                           |

---

## n8n Workflow Setup

Here's exactly how to build this in n8n:

### Step 1 — Webhook (you already have this)

Your trigger node receives the data.

### Step 2 — IF Node (Filter for your specific group)

Add an **IF** node to only proceed if the message is from your target group.

- **Field:** `{{$json.body.data.key.remoteJid}}`
- **Operation:** `equals`
- **Value:** `120363367748965795@g.us` ← your group's ID

> You can also filter broadly for **any group** by checking if `remoteJid` ends with `@g.us` using the **contains** operation.

### Step 3 — IF Node (Filter for image messages only, optional)

If you want only image messages (not plain text):

- **Field:** `{{$json.body.data.messageType}}`
- **Operation:** `equals`
- **Value:** `imageMessage`

### Step 4 — Set Node (Extract the fields you need)

Use a **Set** node to pull out clean values:

| Field Name      | Expression                                         |
| --------------- | -------------------------------------------------- |
| `sender_name`   | `{{$json.body.data.pushName}}`                     |
| `sender_number` | `{{$json.body.data.key.participantAlt}}`           |
| `group_id`      | `{{$json.body.data.key.remoteJid}}`                |
| `image_url`     | `{{$json.body.data.message.imageMessage.url}}`     |
| `caption`       | `{{$json.body.data.message.imageMessage.caption}}` |
| `timestamp`     | `{{$json.body.data.messageTimestamp}}`             |

### Step 5 — Google Sheets Node

Connect to **Google Sheets** → **Append Row**, and map each field above to a column.

---

## One Important Note on the Image URL

The `imageMessage.url` is a **temporary WhatsApp CDN link** — it expires. If you want a permanent copy of the image, you'd need to add an **HTTP Request** node between the Set node and Google Sheets to download the image and upload it to Google Drive, then store the Drive link instead. Let me know if you want help with that part too!

Based on your JSON, the `messageType` field tells you what kind of message was sent. Here are the main types you'll encounter in WhatsApp:

---

## Message Types & Their Paths

### 1. `imageMessage` — Image only OR image with caption

- The one in your data. Caption is **optional**, so if someone sends just an image with no text, `caption` will be absent/null.
- Image URL → `body.data.message.imageMessage.url`
- Caption → `body.data.message.imageMessage.caption` _(may not exist)_

### 2. `conversation` — Plain text message only

- Just a text message, no media attached.
- Message text → `body.data.message.conversation`

### 3. `extendedTextMessage` — Text with a link preview

- When someone sends a URL and WhatsApp generates a preview card.
- Message text → `body.data.message.extendedTextMessage.text`

### 4. `videoMessage` — Video only OR video with caption

- Caption → `body.data.message.videoMessage.caption` _(may not exist)_
- URL → `body.data.message.videoMessage.url`

### 5. `documentMessage` — A file/document (PDF, Word, etc.)

- Caption → `body.data.message.documentMessage.caption`
- File name → `body.data.message.documentMessage.fileName`

### 6. `audioMessage` — Voice note or audio file

- URL → `body.data.message.audioMessage.url`

### 7. `stickerMessage` — A sticker

- URL → `body.data.message.stickerMessage.url`

---

## How to Handle This in n8n

Since you want both plain text messages AND image+caption messages, the tricky part is that the text lives in **different paths** depending on the type. The cleanest way to handle this is with a **Switch node** after your group filter:

**Switch node** on `{{$json.body.data.messageType}}`:

- **Case 1:** `imageMessage` → Set node pulling `imageMessage.url` + `imageMessage.caption`
- **Case 2:** `conversation` → Set node pulling `message.conversation` as the text, image URL = blank
- **Case 3:** `extendedTextMessage` → Set node pulling `extendedTextMessage.text`, image URL = blank

All three branches then feed into the same **Google Sheets** node, so every row has consistent columns like `sender_name`, `message_text`, `image_url`, and `timestamp` — just with some fields blank depending on the type.

---

Want me to help you set up the Switch node logic or the Google Sheets column structure?

# Teamspeak 6 Matrix Credential Extractor

This is a tool built for extracting your Matrix credentials from Teamspeak 6 to access the chat functionalities from Matrix compatible clients.

## Usage
Using the sidebar, load your `settings.db. You can find it in the locations listed below:

- Windows: `%APPDATA%\TeamSpeak\Default`
- Linux: `~/.config/TeamSpeak/Default`
- Mac: `~/Library/Preferences/TeamSpeak/Default`

## Limitations
Only unencrypted group chats will work properly, encrypted chat is extremely flakey.

Teamspeak has various custom tools built-on top of the Matrix protocol
so not everything is supported/compatible. **Use at your own risk**

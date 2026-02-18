
## What It Does

- ✅ **Task Management** - Add, view, and complete tasks
- 📰 **News Tracking** - Get latest headlines
- 📈 **Market Updates** - Check stock prices
- 💬 **Natural Conversation** - Chat naturally with your AI assistant

## Quick Start

### 1. Install Dependencies
```bash
pip3 install -r requirements.txt
```

### 2. Set Up Your API Keys
Create a `.env` file:
```
ANTHROPIC_API_KEY=sk-ant-your-key-here
# Optional: for Economic Calendar "Recent releases" (FRED data)
# FRED_API_KEY=your-fred-key
```
Get a free FRED API key at https://fred.stlouisfed.org/docs/api/api_key.html

### 3. Run Your Agent
```bash
python3 agent.py
```

## Example Conversations
```
You: Add task: Buy groceries
🤖 Agent: ✅ Task added: Buy groceries

You: Show my tasks
🤖 Agent: 📋 Your Tasks:
○ [1] Buy groceries

You: What's in the news?
🤖 Agent: 📰 Latest Headlines...

You: Complete task 1
🤖 Agent: ✅ Completed: Buy groceries
```

## Files in This Project

- `agent.py` - Main agent code (we'll create this next!)
- `requirements.txt` - Python dependencies
- `.env` - Your API key 
- `.gitignore` - Files to keep private
- `my_tasks.json` - Your tasks (auto-created when you use it)

## Next Steps

Want to add real news and market data? Check out the tutorial files!


"""
LIFE MANAGEMENT AGENT - Starter Version
For beginners learning Python and AI agents

This agent can:
- Chat with you naturally
- Manage tasks and to-dos
- Fetch news headlines
- Check stock market prices
- Help organize thoughts

HOW TO USE:
1. Make sure you've completed the setup guide
2. Run: python3 agent.py
3. Start chatting!
"""

import math
import os
import json
from datetime import datetime
from dotenv import load_dotenv
from anthropic import Anthropic
import yfinance as yf  

# Load your API key from .env file
load_dotenv()

# Initialize Claude
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Where we'll store tasks and notes
TASKS_FILE = "my_tasks.json"
NOTES_FILE = "my_notes.json"


# ============================================
# HELPER FUNCTIONS (The tools for your agent)
# ============================================

def load_tasks():
    """Load your task list from a file"""
    if os.path.exists(TASKS_FILE):
        with open(TASKS_FILE, 'r') as f:
            return json.load(f)
    return []


def save_tasks(tasks):
    """Save your task list to a file"""
    with open(TASKS_FILE, 'w') as f:
        json.dump(tasks, f, indent=2)


def add_task(task_description):
    """Add a new task to your list"""
    tasks = load_tasks()
    new_task = {
        "id": len(tasks) + 1,
        "description": task_description,
        "completed": False,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    tasks.append(new_task)
    save_tasks(tasks)
    return f"✅ Task added: {task_description}"


def list_tasks():
    """Show all your tasks"""
    tasks = load_tasks()
    if not tasks:
        return "You have no tasks yet. Add one by saying 'add task: [description]'"
    
    result = "📋 Your Tasks:\n\n"
    for task in tasks:
        status = "✓" if task["completed"] else "○"
        result += f"{status} [{task['id']}] {task['description']}\n"
    return result


def complete_task(task_id):
    """Mark a task as completed"""
    tasks = load_tasks()
    for task in tasks:
        if task["id"] == task_id:
            task["completed"] = True
            save_tasks(tasks)
            return f"✅ Completed: {task['description']}"
    return f"❌ Task {task_id} not found"


def get_news_headlines():
    """
    Fetch latest news headlines
    NOTE: This is a simplified version. You'll need a real news API later.
    """
    return """
📰 Latest Headlines (Demo):

1. Tech stocks rally on AI optimism
2. Climate summit reaches new agreement
3. Local team wins championship
4. New research on renewable energy

(To get real news, you'll need to set up a news API like NewsAPI.org)
"""


import yfinance as yf

def get_market_data():
    """Check real-time stock market prices"""
    try:
        # Major market indices
        symbols = {
            '^GSPC': 'S&P 500',
            '^IXIC': 'NASDAQ',
            '^DJI': 'Dow Jones'
        }
        
        result = "📈 Market Update (Real-Time):\n\n"
        
        for symbol, name in symbols.items():
            ticker = yf.Ticker(symbol)
            data = ticker.history(period='1d')
            
            if not data.empty:
                current_price = float(data['Close'].iloc[-1])
                prev_close = ticker.info.get('previousClose', current_price)
                prev_close = float(prev_close) if prev_close is not None else current_price
                if prev_close and prev_close != 0 and not math.isnan(prev_close):
                    change = current_price - prev_close
                    change_percent = (change / prev_close) * 100
                else:
                    change = 0.0
                    change_percent = 0.0
                result += f"{name}: ${current_price:,.2f}\n"
                result += f"Change: {change:+.2f} ({change_percent:+.2f}%)\n\n"
        
        return result
    except Exception as e:
        return f"❌ Couldn't fetch market data: {e}\nTry again in a moment."


# ============================================
# THE AGENT BRAIN
# ============================================

def chat_with_agent(user_message, conversation_history):
    """
    This is where the magic happens!
    Claude reads your message, decides what to do, and responds.
    """
    
    # Build the system prompt (tells Claude what it can do)
    system_prompt = f"""You are a helpful life management assistant. Today is {datetime.now().strftime("%B %d, %Y")}.

You can help the user with:
1. Task management (add, list, complete tasks)
2. News updates
3. Market information
4. General conversation and organization

When the user wants to:
- Add a task: Call add_task with the description
- See tasks: Call list_tasks
- Complete a task: Call complete_task with the task number
- Get news: Call get_news_headlines
- Check markets: Call get_market_data

Be friendly, helpful, and proactive. If you notice the user needs help organizing something, suggest it!
"""
    
    # Add the new message to history
    conversation_history.append({
        "role": "user",
        "content": user_message
    })
    
    # Ask Claude to respond
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=system_prompt,
        messages=conversation_history
    )
    
    # Get Claude's response
    assistant_message = response.content[0].text
    
    # Check if Claude wants to use any tools
    if "add task:" in user_message.lower():
        task_desc = user_message.lower().split("add task:")[-1].strip()
        tool_result = add_task(task_desc)
        assistant_message = tool_result
    elif "list task" in user_message.lower() or "show task" in user_message.lower():
        assistant_message = list_tasks()
    elif "complete task" in user_message.lower():
        try:
            task_num = int(''.join(filter(str.isdigit, user_message)))
            assistant_message = complete_task(task_num)
        except:
            assistant_message = "Please specify which task number to complete"
    elif "news" in user_message.lower() or "headlines" in user_message.lower():
        assistant_message = get_news_headlines()
    elif "market" in user_message.lower() or "stock" in user_message.lower():
        assistant_message = get_market_data()
    
    # Add Claude's response to history
    conversation_history.append({
        "role": "assistant",
        "content": assistant_message
    })
    
    return assistant_message, conversation_history


# ============================================
# MAIN PROGRAM - This runs when you start the agent
# ============================================

def main():
    """The main loop - keeps the conversation going"""
    
    print("\n" + "="*50)
    print("🤖 LIFE MANAGEMENT AGENT")
    print("="*50)
    print("\nHello! I'm your personal AI assistant.")
    print("I can help you with tasks, news, markets, and more!")
    print("\nTry saying:")
    print("  - 'Add task: Buy groceries'")
    print("  - 'Show my tasks'")
    print("  - 'What's in the news?'")
    print("  - 'Check the market'")
    print("\nType 'quit' to exit.\n")
    
    # Keep track of the conversation
    conversation_history = []
    
    # Main loop - keep chatting until user quits
    while True:
        # Get user input
        user_input = input("You: ").strip()
        
        # Check if user wants to quit
        if user_input.lower() in ['quit', 'exit', 'bye']:
            print("\n👋 Goodbye! Your tasks are saved for next time.\n")
            break
        
        # Skip empty messages
        if not user_input:
            continue
        
        # Get response from agent
        try:
            response, conversation_history = chat_with_agent(user_input, conversation_history)
            print(f"\n🤖 Agent: {response}\n")
        except Exception as e:
            print(f"\n❌ Error: {e}")
            print("Make sure your API key is set up correctly!\n")
            break


# ============================================
# START THE AGENT
# ============================================

if __name__ == "__main__":
    main()
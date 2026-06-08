Building a completely 100% free architecture for your MVP (Minimum Viable Product) is entirely possible. The modern developer ecosystem offers incredibly generous "forever free" tiers that are more than capable of handling a 12-member lottery pool and the admin dashboard.  
Since you will be using Claude Code to generate the application, you need a stack that is highly standardized so the AI can write it flawlessly. Leveraging Python for the backend will be perfect for writing the AI dual-draw algorithmic logic.  
Here is your **100% Free Tech Stack Blueprint**, and exactly how to set it up when configuring your Git environment and workspaces under your Amosder handle.

### **1\. The 100% Free Tech Stack**

**The Database: Supabase (PostgreSQL)**

* **Why:** Supabase gives you a massive 500MB free PostgreSQL database. It is incredibly fast, highly secure, and perfect for managing your Deposit/Withdraw tokens and user ledgers.  
* **Cost:** $0/month.

**The Backend (API & Logic): Render**

* **Why:** Render allows you to host a Python web service completely for free. We will use **FastAPI** (Python) here. It is lightweight, ultra-fast, and AI coding assistants excel at writing it. This is where your Sunday draw logic, token generation, and 24-member waitlist scaling will live.  
* **Cost:** $0/month. *(Note: Render's free tier "spins down" your backend if no one uses it for 15 minutes. It takes about 30 seconds to wake up on the next request, which is perfectly fine for a free MVP).*

**The Frontend (User & Admin UI): Vercel**

* **Why:** Vercel is the undisputed king of free frontend hosting. You will build a **React.js (Vite)** application styled with **Tailwind CSS**. Vercel will host your mobile web app globally on a super-fast CDN, completely for free.  
* **Cost:** $0/month.

### **2\. How to Guide Claude Code (The Development Flow)**

AI coding tools work best when you break the project into smaller, distinct modules. Do not ask it to build the whole lottery system in one prompt. Follow this exact sequence:  
**Phase 1: Database & Backend Initialization**

1. Create a free account on Supabase, spin up a new project, and grab your database connection string.  
2. Open your terminal, start Claude Code, and use this prompt:*"Create a new Python FastAPI backend. Set up a PostgreSQL database connection using SQLAlchemy. Create the database models for 'Users' (Name, Mobile, Join Date, Pool Status), 'Pools' (Pool A, Pool B), and 'Tokens' (Token String, Type: Deposit/Withdraw, Value, Status: Active/Burned)."*

**Phase 2: The Admin Logic**

1. Once the database is connected, prompt the AI to build the Admin routes:*"Create secure API endpoints for the Admin. I need an endpoint to generate a Deposit Token with a specific ₹ value, and an endpoint to verify and 'burn' a Withdraw Token when a user cashes out."*

**Phase 3: The AI Draw & Waitlist Logic**

1. Prompt the AI for the core business logic:*"Write the lottery draw logic. Create a function that triggers every Sunday at 7 PM. It must strictly pull 2 winners from the active 12-member pool (one from L1-L3, one from L4-L6). Also, write the auto-scaling logic: if the waitlist reaches 24 members with paid Deposit Tokens, automatically create 'Pool B' and move the top 12 users into it."*

**Phase 4: The Frontend UI (React \+ Tailwind)**

1. Create a separate folder for your frontend, connect it to Vercel, and ask Claude Code to build the interfaces:*"Initialize a React Vite application with Tailwind CSS and Framer Motion. Build a futuristic, glassmorphism mobile UI. Create a User Dashboard showing their current Pool, next draw countdown, and an input field to redeem a Deposit Token."*

### **3\. The Only "Costs" to Keep in Mind**

While the software, hosting, databases, and bandwidth are completely free, there are two minor things you will eventually need:

* **A Custom Domain Name:** Vercel gives you a free domain (e.g., amosder-lottery.vercel.app), but for trust, you might eventually want to spend ₹800/year on a .com or .in domain.  
* **SMS/WhatsApp Notifications:** There are no truly free, high-volume WhatsApp APIs. For the MVP, you can have the system send free email notifications, or manually copy-paste the Sunday draw alerts into a WhatsApp Broadcast list.

To get started with generating the code, which part of the system do you want to instruct Claude Code to build first—the Python FastAPI backend or the React user interface?
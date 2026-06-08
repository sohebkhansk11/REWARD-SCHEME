To build and launch this system quickly with ultra-rich graphics, a **Mobile-Optimized Web Application (Progressive Web App or PWA)** is definitively the better, faster, and safer choice compared to a native Android application.  
Here is the straightforward reality: Native Android apps that involve financial pools, lotteries, or tokenized cash-outs face brutal scrutiny and high rejection rates from the Google Play Store. By building a highly advanced mobile web app, you completely bypass App Store restrictions, avoid paying Google's 30% in-app purchase fees, and can deploy instant updates to your users.  
Here is the architectural blueprint to achieve that futuristic UI and real-time backend functionality.

### **1\. The Recommended Tech Stack**

To handle the AI pairing algorithms, cloud execution, and high-end graphics efficiently, this stack is ideal:

* **Backend (The Brain):** **Python (FastAPI or Django).** Python is exceptionally powerful for handling the algorithmic logic (like your AI Smart Pairing and 24-member pool splitting), and FastAPI is incredibly fast for handling concurrent web requests.  
* **Frontend (The Visuals):** **React.js or Vue.js.** These frameworks allow you to build an app-like experience that runs smoothly in a mobile browser.  
* **Styling (Futuristic UI):** **Tailwind CSS** combined with **Framer Motion**. This allows you to create modern "Glassmorphism" designs (translucent, blurred backgrounds, neon glowing borders) with fluid, 60fps animations.  
* **Database:** **PostgreSQL.** It is highly secure and perfect for maintaining precise ledgers for your Deposit/Withdraw tokens.

### **2\. Implementing the Ultra-Rich UI Features**

**A. User Registration & Profile Generation**

* During signup, the user inputs their Name and Mobile Number.  
* For the Username, provide a toggle: they can either type a custom handle, or click a "Generate" button where the system instantly creates a futuristic ID (e.g., User-X99-Alpha).  
* The user dashboard will prominently display their Join Date, Active Pool Status (e.g., "Pool A \- Week 3"), and their real-time win probability.

**B. The Sunday 7 PM Animated Draw (Real-Time Sync)**  
This is where you build the excitement and FOMO.

* Instead of heavy GIF or video files, use **Lottie Animations** (JSON-based animations). They are ultra-lightweight, load instantly, and look incredibly crisp on mobile screens.  
* Use **WebSockets** for the backend connection. At exactly 6:59:50 PM on Sunday, the WebSocket triggers a live 10-second countdown on every active user's screen simultaneously.  
* At 7:00 PM, a sleek, casino-style randomized roulette or futuristic data-decryption animation plays, stopping dramatically on the two winners' usernames.

**C. Notification System**  
Since a web app cannot easily send native push notifications on iOS without specific user settings, you integrate **WhatsApp API** or **SMS API (like Twilio)**.

* The system can automatically text users: *"Your Sunday Draw begins in 1 hour\! Log in now."*  
* It also automates the Penalty countdowns: *"Warning: 2 hours left to pay your ₹1,000 Revival Penalty before your L4 spot is forfeited."*

### **3\. The Admin Panel Architecture**

The Admin dashboard needs to be a distinct, highly secure portal separate from the user-facing app.

* **Token Generator Module:** A dedicated screen where you input the fiat/USDT amount received, and the system generates the unique Deposit Token string (e.g., DEP-8A9X-1000) for you to copy and send to the user.  
* **Pool Oversight:** Visual cards showing the status of Pool A, Pool B, etc., highlighting exactly who has paid, who is pending, and who is in the "Elimination Zone."  
* **Waitlist Manager:** A dynamic list showing users waiting to enter, automatically triggering the "New Pool Creation" when the counter hits 24\.

By hosting this as a cloud-based web application, your users simply tap a link, log in, and experience a high-end application entirely within their mobile browser, while you maintain absolute control over the financial gateway.  
Are you planning to deploy this infrastructure on AWS, or do you have a preferred cloud environment for running the Python backend and database?
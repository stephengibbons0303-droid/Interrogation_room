import os
import random
from typing import Dict, Any
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

# Load environment variables
load_dotenv()

class InterrogationAgent:
    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.llm = None
        self.history = []
        self.last_agent = "Reynolds" # Start with Reynolds context
        self.vector_store = None
        
        if self.api_key:
            self.llm = ChatOpenAI(model="gpt-4o", temperature=0.7)
            # Initialize Vector Store (ChromaDB)
            # We use a persistent directory so memory survives restarts if needed, 
            # but for now standard local is fine.
            self.vector_store = Chroma(
                collection_name="interrogation_memory",
                embedding_function=OpenAIEmbeddings(model="text-embedding-3-small"),
                persist_directory="./chroma_db" 
            )
        else:
            print("WARNING: No OPENAI_API_KEY found. Falling back to Mock Mode.")

    def process_message(self, user_message: str) -> Dict[str, Any]:
        self.history.append({"role": "user", "content": user_message})
        
        if not self.llm:
            return self._mock_fallback(user_message)

        try:
            # Silence Handling Logic
            is_silence = user_message.strip() == "[SILENCE]"
            
            # Vector Memory Retrieval (The "Lie Detector")
            relevant_context = ""
            if self.vector_store and not is_silence:
                # Search for past statements similar to current input
                results = self.vector_store.similarity_search(user_message, k=2)
                if results:
                    docs_content = [doc.page_content for doc in results]
                    relevant_context = "\n".join([f"- {content}" for content in docs_content])
            
            # Turn Logic: Breaking the A-B-A-B pattern
            # Goal: More Bad Cop (Reynolds), Good Cop (Chen) only interjects occasionally
            
            if is_silence:
                # If silent, Reynolds dominates (80%) to pressure
                current_agent = "Reynolds" if random.random() > 0.2 else "Chen"
            else:
                if self.last_agent == "Reynolds":
                    # If Reynolds just spoke, he has 70% momentum to keep pressing
                    current_agent = "Reynolds" if random.random() > 0.3 else "Chen"
                else:
                    # If Chen just spoke, highly likely (85%) to switch back to Reynolds
                    # She makes her point, then he takes over again.
                    current_agent = "Reynolds" if random.random() > 0.15 else "Chen"
            
            self.last_agent = current_agent
            
            # Pass relevant vector context to the prompt generator
            system_prompt = self._get_prompt(current_agent, is_silence, relevant_context)
            
            # Build Context Window (Last 10 turns)
            # CRITICAL FIX: Including Agent responses so they remember what they said
            context_messages = []
            for msg in self.history[-10:]:
                if msg["role"] == "user":
                    context_messages.append(HumanMessage(content=msg["content"]))
                else:
                    # Label the agent so the model knows who said what previously
                    agent_label = msg.get("agent", "Agent")
                    context_messages.append(AIMessage(content=f"[{agent_label}]: {msg['content']}"))

            messages = [
                SystemMessage(content=system_prompt),
                *context_messages
            ]
            
            # Generate response
            response = self.llm.invoke(messages)
            response_text = response.content
            
            # Save Agent Response to History
            self.history.append({
                "role": "assistant",
                "content": response_text,
                "agent": current_agent
            })

            # Save USER message to Vector DB (Long Term Memory)
            # We do this AFTER processing so it doesn't match itself immediately in the query above
            if self.vector_store and not is_silence:
                self.vector_store.add_texts(texts=[user_message])
            
            # Simple emotion mapping based on agent
            emotion = "stern" if current_agent == "Reynolds" else "supportive"
            
            return {
                "text": response_text,
                "agent": current_agent,
                "emotion": emotion
            }
            
        except Exception as e:
            print(f"Error invoking LLM: {e}")
            return self._mock_fallback(user_message)

    def _get_prompt(self, agent_name: str, is_silence: bool = False, vector_context: str = "") -> str:
        silence_instruction = ""
        vector_instruction = ""

        if vector_context:
             vector_instruction = f"\nRELEVANT PAST STATEMENTS FROM WITNESS (CHECK FOR CONTRADICTIONS):\n{vector_context}\nIf they contradict these past statements, call them out immediately!"

        if is_silence:
            if agent_name == "Reynolds":
                strategies = [
                    "Accuse them of stalling to invent a lie.",
                    "Interpret their silence as an admission of guilt.",
                    "Mock their freezing up ('Cat got your tongue?').",
                    "Threaten with Obstruction of Justice charges.",
                    "Impatiently tap the table and demand an answer NOW.",
                    "Suggest they are protecting someone."
                ]
                selected_strategy = random.choice(strategies)
                silence_instruction = f"THE USER HAS BEEN SILENT FOR 10 SECONDS. React to this silence using this specific strategy: {selected_strategy}"
            else:
                strategies = [
                    "Offer them a glass of water or a moment to breathe.",
                    "Suggest they are intimidated by Detective Reynolds.",
                    "Validate that it is a difficult situation/question.",
                    "Gently remind them that the truth is the only way out.",
                    "Ask if they are afraid of repercussions."
                ]
                selected_strategy = random.choice(strategies)
                silence_instruction = f"THE USER HAS BEEN SILENT FOR 10 SECONDS. React to this silence using this specific strategy: {selected_strategy}"

        if agent_name == "Reynolds":
            return f"""You are Detective James Reynolds (Bad Cop).
            You are interrogating a witness (the user) about the disappearance of Emily Parker.
            Your Goal: Pressure the witness. Find inconsistencies. Be impatient, skeptical, and intimidating.
            Style: Short, sharp sentences. Use the user's name formally (if known).
            {vector_instruction}
            {silence_instruction}
            
            If not silent but user gives short answers: Press for details.
            If user denies: Mock their denial."""
        else:
            return f"""You are Detective Sarah Chen (Good Cop).
            You are interrogating a witness (the user) about the disappearance of Emily Parker.
            Your Goal: Build rapport. De-escalate Reynolds' aggression. Get them to open up.
            Style: Warm, understanding, soft-spoken.
            {vector_instruction}
            {silence_instruction}
            
            If not silent: Focus on the 'why' and feelings. Try to find a common ground."""

    def _mock_fallback(self, user_message: str):
        # Fallback if no key
        return {
            "text": "[MOCK] Please add OPENAI_API_KEY to .env to enable real responses. " + 
                   f"You said: {user_message}",
            "agent": "System",
            "emotion": "neutral"
        }

# Singleton
agent_instance = InterrogationAgent()

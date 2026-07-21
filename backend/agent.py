import os
import random
from typing import Dict, Any, List
from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings, ChatOpenAI, OpenAIEmbeddings
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.embeddings import Embeddings
from langchain_chroma import Chroma


class LocalEmbeddings(Embeddings):
    """LangChain adapter over the ONNX MiniLM model bundled with chromadb.

    Fallback for when there is no embedding deployment available - the Azure
    resource currently only has a chat deployment, and embeddings need their own.
    Runs locally on the already-installed onnxruntime: no key, no cost, no
    network after the ~80 MB model is fetched once. Lower quality than
    text-embedding-3-small, but this only has to surface semantically similar
    prior statements for contradiction detection, not power a search engine.
    """

    def __init__(self):
        from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
        self._fn = ONNXMiniLM_L6_V2()

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [[float(x) for x in vec] for vec in self._fn(list(texts))]

    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# NARRATIVE PHASES - The player discovers the situation gradually
# ─────────────────────────────────────────────────────────────────────────────
NARRATIVE_PHASES = {
    1: {
        "name": "ORIENTATION",
        "turn_range": (0, 4),
        "description": "Establish setting. Player knows nothing. Detectives ask identity questions, "
                       "make them uneasy. No details about the case yet.",
        "evidence_available": [],
        "reynolds_tone": "coldly procedural, sizing them up",
        "chen_tone": "politely distant, taking notes",
        "reveal": "You are in an interview room. You have been asked to come in voluntarily. "
                  "The detectives have not told you why."
    },
    2: {
        "name": "THE HOOK",
        "turn_range": (5, 10),
        "description": "First hint something is wrong. Mention a person's name - 'Emily Parker' - "
                       "and watch for reaction. Ask about the player's relationship to her.",
        "evidence_available": ["Emily Parker has been reported missing since last Thursday evening."],
        "reynolds_tone": "watching every micro-expression, beginning to apply pressure",
        "chen_tone": "sympathetic but probing, framing questions as concern for Emily",
        "reveal": "A woman named Emily Parker has gone missing. They seem to think you know her."
    },
    3: {
        "name": "THE TIGHTENING",
        "turn_range": (11, 18),
        "description": "Introduce timeline pressure. Where were you Thursday between 5pm and midnight? "
                       "Drop specific details that imply the player was seen near Emily's last known location.",
        "evidence_available": [
            "Emily Parker has been reported missing since last Thursday evening.",
            "Emily's phone last pinged at 9:47pm near the Canal Street bridge.",
            "A witness reported seeing someone matching the player's general description in the area at approximately 9:30pm.",
            "Emily sent a text to a friend at 8:15pm saying she was 'meeting someone to sort things out.'"
        ],
        "reynolds_tone": "aggressive, confrontational, hammering timeline inconsistencies",
        "chen_tone": "reasonable but firm, offering the player chances to explain things that look bad",
        "reveal": "Emily's phone died near Canal Street bridge at 9:47pm. A witness saw someone "
                  "matching your description nearby. They are trying to build a timeline."
    },
    4: {
        "name": "THE TRAP",
        "turn_range": (19, 28),
        "description": "Confront with harder evidence. Introduce the player's phone records, a possible "
                       "motive, or a prior relationship. Force them to explain increasingly damning coincidences.",
        "evidence_available": [
            "Emily Parker has been reported missing since last Thursday evening.",
            "Emily's phone last pinged at 9:47pm near the Canal Street bridge.",
            "A witness reported seeing someone matching the player's general description in the area at approximately 9:30pm.",
            "Emily sent a text to a friend at 8:15pm saying she was 'meeting someone to sort things out.'",
            "Phone records show the player received two calls from Emily's number that Thursday - at 4:12pm and 7:58pm.",
            "The player's phone pinged a tower consistent with the Canal Street area between 9:15pm and 10:20pm.",
            "Emily's colleague mentioned Emily had been in a dispute with someone - she wouldn't say who.",
            "CCTV from a nearby shop shows a figure in a dark jacket walking toward the bridge at 9:38pm."
        ],
        "reynolds_tone": "relentless, treating them as a suspect not a witness, daring them to explain the evidence",
        "chen_tone": "quietly concerned, suggesting that things look very bad and cooperation is their best option",
        "reveal": "Your phone was in the Canal Street area that night. Emily called you twice. "
                  "They have CCTV of someone near the bridge. The interview has shifted - you feel less like a witness."
    },
    5: {
        "name": "THE RECKONING",
        "turn_range": (29, 999),
        "description": "Final phase. Everything converges. Detectives present a theory of what happened "
                       "and challenge the player to disprove it. Emotional peak.",
        "evidence_available": [
            "Emily Parker has been reported missing since last Thursday evening.",
            "Emily's phone last pinged at 9:47pm near the Canal Street bridge.",
            "A witness reported seeing someone matching the player's general description in the area at approximately 9:30pm.",
            "Emily sent a text to a friend at 8:15pm saying she was 'meeting someone to sort things out.'",
            "Phone records show the player received two calls from Emily's number that Thursday - at 4:12pm and 7:58pm.",
            "The player's phone pinged a tower consistent with the Canal Street area between 9:15pm and 10:20pm.",
            "Emily's colleague mentioned Emily had been in a dispute with someone - she wouldn't say who.",
            "CCTV from a nearby shop shows a figure in a dark jacket walking toward the bridge at 9:38pm.",
            "Forensic analysis of Emily's flat shows signs it was cleaned recently - not consistent with her usual habits.",
            "Emily's bank card was used at a petrol station at 11:02pm Thursday - 3 miles from Canal Street, toward the motorway.",
            "A partial shoe print was found on the canal towpath matching a common trainer brand."
        ],
        "reynolds_tone": "prosecutorial, building the case aloud, daring them to break",
        "chen_tone": "grave, almost sad, telling them this is their last real chance to tell the truth",
        "reveal": "They have a theory. They believe you met Emily that night, something happened at the bridge, "
                  "and you tried to cover your tracks. Everything they've presented points at you."
    }
}

# ─────────────────────────────────────────────────────────────────────────────
# DETECTIVE PROFILES
# ─────────────────────────────────────────────────────────────────────────────

REYNOLDS_PROFILE = """You are Detective Inspector James Reynolds, Metropolitan Police, Major Crimes Unit.

BACKGROUND:
- 22 years on the force. Started as a beat constable in Brixton, made Detective by 28.
- Worked organised crime for a decade before transferring to Major Crimes after a case involving a missing university student that he solved but that haunted him.
- Divorced. His ex-wife said he could never leave the job at the door. She was right.
- Known in the department as "The Closer" - not because he's charming, but because he doesn't stop.
- Has a near-photographic memory for details. If you said something 20 minutes ago that contradicts what you're saying now, he noticed.

INTERROGATION PHILOSOPHY:
- Believes everyone lies in an interview room. His job is to make lying harder than telling the truth.
- Uses the PEACE model framework but pushes its boundaries. His "challenge" phase is legendary.
- Doesn't shout. Doesn't need to. His weapon is precision - he lays out facts like a surgeon and waits for the subject to squirm.
- Occasionally uses strategic silence himself. Lets uncomfortable truths hang in the air.
- Masters the "assumptive question" - phrasing questions as though the answer is already known.

VERBAL STYLE:
- Clipped, direct sentences. Never wastes a word.
- Uses the subject's surname formally: "Mr [name]" or "Ms [name]."
- Dry, dark humour that surfaces when he's cornering someone. Not cruel - controlled.
- Favours rhetorical questions: "You see how that looks, don't you?"
- When reading from evidence, speaks slowly and deliberately, as if each word is a nail.

TACTICAL APPROACHES (rotate these naturally based on context):
1. TIMELINE PRESSURE: Obsessively map every minute. "What time exactly? And after that? And between then and when?"
2. EVIDENCE CONFRONTATION: Present a fact, wait for their explanation, then show why it doesn't hold.
3. COGNITIVE LOAD: Ask the same event from different angles - chronologically, then reverse, then from a specific detail outward.
4. STRATEGIC DISCLOSURE: Reveal evidence piece by piece. Never show the full hand. Let them commit to a story, then introduce the thing that breaks it.
5. MINIMISATION TRAP: Occasionally downplay something ("I'm sure there's a simple explanation...") to invite them to say too much.
6. SILENCE EXPLOITATION: After a damning point, simply stop talking and watch them fill the void.
"""

CHEN_PROFILE = """You are Detective Sergeant Sarah Chen, Metropolitan Police, Major Crimes Unit.

BACKGROUND:
- 12 years on the force. Degree in forensic psychology from King's College London before joining.
- Specialist in cognitive interviewing and witness rapport-building. Published a paper on memory recall under stress.
- Grew up in a multilingual household (Cantonese, English). Fluent reader of body language and conversational subtext.
- Requested Major Crimes specifically because she believes most missing persons cases are solved by getting people to remember things they didn't know they remembered.
- Respected by colleagues for being the one suspects open up to - even when they intended to say nothing.

INTERROGATION PHILOSOPHY:
- Believes people don't lie in a vacuum - they lie because of fear, shame, loyalty, or self-preservation.
  Understanding the "why" behind the lie is more useful than catching it.
- Uses cognitive interviewing techniques: context reinstatement, open-ended prompts, sensory detail recall.
- Plays the long game. While Reynolds breaks down walls, she finds the door.
- Knows when to intervene if Reynolds is pushing too hard - not out of softness, but because a panicked subject shuts down and gives nothing.
- Occasionally lets Reynolds be "the bad guy" deliberately, then uses that tension to build alliance with the subject.

VERBAL STYLE:
- Warm but not soft. Measured. Every kindness has purpose.
- Uses first names. Creates intimacy and lowers defences.
- Asks open questions: "Tell me about that evening. Start wherever feels natural."
- Validates emotions before redirecting: "I can see this is difficult. But I need you to think carefully about..."
- Uses reflective listening - restates what the subject said in slightly different words to make them reconsider or elaborate.

TACTICAL APPROACHES (rotate these naturally based on context):
1. CONTEXT REINSTATEMENT: "Close your eyes for a moment. Picture where you were. What could you see? What could you hear?"
2. EMOTIONAL ANCHORING: Connect questions to feelings. "How were you feeling when Emily called?"
3. ALLIANCE BUILDING: Position herself on the subject's side. "I want to help you clear this up."
4. STRATEGIC EMPATHY: Validate their position, then pivot. "I understand why you'd say that. But then how do you explain...?"
5. DETAIL EXPANSION: Pick one small detail and unfold it. "You mentioned you were at home. What were you watching on TV?"
6. NARRATIVE INVITATION: Let them tell a long story uninterrupted, then return to the inconsistencies.
"""

# ─────────────────────────────────────────────────────────────────────────────
# SILENCE RESPONSE STRATEGIES
# ─────────────────────────────────────────────────────────────────────────────

REYNOLDS_SILENCE_STRATEGIES = [
    "Let the silence stretch for a beat, then say something like 'The thing about silence, "
    "Mr/Ms [name], is that it tells me you're thinking. And I have to wonder what you're thinking about.'",

    "Flip open a folder (real or implied) and read something quietly to yourself, as if the subject "
    "isn't even there. Then look up and say 'Sorry, just checking something. Where were we?'",

    "Lean forward. Lower your voice. 'I'm going to give you a piece of advice. Free of charge. "
    "The longer you sit there saying nothing, the worse this gets. I've seen it a hundred times.'",

    "Tap the table once. 'We've got all night. I don't. But the custody clock is your problem, not mine.'",

    "Address Chen as if the subject isn't there: 'DS Chen, mark the time. Subject is declining to respond.'",

    "Stand up, walk toward the door as if leaving, then pause. "
    "'Last chance before I go talk to the people who are a lot less patient than me.'"
]

CHEN_SILENCE_STRATEGIES = [
    "Soften your posture. 'Take your time. I know this is a lot. But I need to hear from you - "
    "not because I'm trying to catch you out, but because right now, your silence is doing you no favours.'",

    "Offer a glass of water. Use the pause to say 'When you're ready. I'm not going anywhere.'",

    "Reference something they said earlier with warmth. 'You told me earlier about [something]. "
    "I believed you when you said that. Help me keep believing you.'",

    "Glance at Reynolds, then back. 'He's going to draw his own conclusions from your silence. "
    "I'd rather hear your version.'",

    "Lower your voice, almost conspiratorial. 'Between you and me - is there something you're scared of? "
    "Because there are things we can do to help. But not if you don't talk to me.'"
]


# ─────────────────────────────────────────────────────────────────────────────
# SHARED RESOURCES
#
# The LLM client and the vector store are expensive to construct and safe to
# share, so they are built once per process. Only conversation state is
# per-interview - see InterrogationAgent below.
# ─────────────────────────────────────────────────────────────────────────────

_LLM = None
_VECTOR_STORE = None
_RESOURCES_READY = False


def _build_llm():
    """Azure OpenAI if configured, else OpenAI, else None (Mock Mode)."""
    if os.getenv("AZURE_OPENAI_API_KEY") and os.getenv("AZURE_OPENAI_ENDPOINT"):
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
        print(f"LLM: Azure OpenAI, deployment '{deployment}'")
        return AzureChatOpenAI(
            azure_deployment=deployment,
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
            temperature=0.75,
        )
    if os.getenv("OPENAI_API_KEY"):
        print("LLM: OpenAI gpt-4o")
        return ChatOpenAI(model="gpt-4o", temperature=0.75)
    return None


def _build_vector_store():
    """Vector memory for contradiction detection. Needs a separate embedding
    deployment on Azure - if there isn't one, we fall back to local."""
    embeddings = None
    tag = None
    azure_embed = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
    if azure_embed and os.getenv("AZURE_OPENAI_API_KEY"):
        embeddings = AzureOpenAIEmbeddings(
            azure_deployment=azure_embed,
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
        )
        tag = "azure"
    elif os.getenv("OPENAI_API_KEY"):
        embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
        tag = "openai"
    else:
        # No hosted embeddings available - fall back to local rather than
        # losing contradiction detection entirely.
        try:
            embeddings = LocalEmbeddings()
            tag = "local"
            print("Embeddings: local ONNX MiniLM (no embedding deployment found)")
        except Exception as e:
            print(f"WARNING: local embeddings unavailable ({e})")
            return None

    if embeddings is None:
        return None
    try:
        # Collection is namespaced per embedding backend. Chroma fixes a
        # collection's dimensionality at creation, and these models disagree
        # (MiniLM 384 vs text-embedding-3-small 1536), so sharing one
        # collection fails with a dimension mismatch on every write.
        return Chroma(
            collection_name=f"interrogation_memory_{tag}",
            embedding_function=embeddings,
            persist_directory="./chroma_db",
        )
    except Exception as e:
        print(f"WARNING: vector store init failed ({e})")
        return None


def init_resources() -> None:
    """Build the shared LLM and vector store once. Safe to call repeatedly."""
    global _LLM, _VECTOR_STORE, _RESOURCES_READY
    if _RESOURCES_READY:
        return
    _RESOURCES_READY = True
    _LLM = _build_llm()
    if _LLM is None:
        print("WARNING: No LLM configured. Falling back to Mock Mode.")
        return
    _VECTOR_STORE = _build_vector_store()
    if _VECTOR_STORE is None:
        # Not fatal - process_message guards on vector_store being None. We
        # lose contradiction detection, not the interview.
        print("WARNING: No embeddings configured - contradiction detection is OFF.")


class InterrogationAgent:
    """One live interrogation.

    Constructed per interview and rehydrated from persisted state, so a learner
    can leave and resume, and nothing is lost across a server restart. Several
    of these coexist - the shared LLM and vector store are process-level.
    """

    def __init__(self, interview_id: str = None, history: List[Dict[str, Any]] = None,
                 turn_count: int = 0, player_name: str = None,
                 last_agent: str = "Reynolds", escalation_score: int = 0,
                 contradiction_count: int = 0):
        init_resources()
        self.interview_id = interview_id
        self.llm = _LLM
        self.vector_store = _VECTOR_STORE
        self.history: List[Dict[str, Any]] = history if history is not None else []
        self.last_agent = last_agent
        self.turn_count = turn_count
        self.player_name = player_name
        self.escalation_score = escalation_score  # how suspicious the player seems
        self.contradiction_count = contradiction_count

    def _get_current_phase(self) -> Dict:
        """Determine current narrative phase based on turn count."""
        for phase_num in sorted(NARRATIVE_PHASES.keys(), reverse=True):
            phase = NARRATIVE_PHASES[phase_num]
            if self.turn_count >= phase["turn_range"][0]:
                return phase
        return NARRATIVE_PHASES[1]

    def _get_phase_number(self) -> int:
        for phase_num in sorted(NARRATIVE_PHASES.keys(), reverse=True):
            phase = NARRATIVE_PHASES[phase_num]
            if self.turn_count >= phase["turn_range"][0]:
                return phase_num
        return 1

    def _determine_agent(self, is_silence: bool) -> str:
        """Determine which detective speaks next using weighted logic."""
        phase_num = self._get_phase_number()

        if is_silence:
            # Higher phases = Reynolds dominates silence more
            reynolds_prob = min(0.6 + (phase_num * 0.06), 0.9)
            return "Reynolds" if random.random() < reynolds_prob else "Chen"

        if self.last_agent == "Reynolds":
            # Reynolds has momentum but Chen interjects more in early phases
            if phase_num <= 2:
                return "Reynolds" if random.random() > 0.4 else "Chen"
            else:
                return "Reynolds" if random.random() > 0.25 else "Chen"
        else:
            # After Chen speaks, Reynolds usually takes back over
            if phase_num <= 2:
                return "Reynolds" if random.random() > 0.3 else "Chen"
            else:
                return "Reynolds" if random.random() > 0.15 else "Chen"

    def _extract_name(self, message: str):
        """Try to extract a name from early responses."""
        if self.player_name:
            return
        # Simple heuristic: if it's an early turn and short, it might be a name
        cleaned = message.strip().rstrip('.').strip()
        words = cleaned.split()
        if len(words) <= 4 and not any(w.lower() in ['yes', 'no', 'why', 'what', 'who', 'where', 'when', 'how', 'i'] for w in words):
            # Likely a name response
            self.player_name = cleaned

    def process_message(self, user_message: str) -> Dict[str, Any]:
        self.history.append({"role": "user", "content": user_message})

        if not self.llm:
            return self._mock_fallback(user_message)

        try:
            is_silence = user_message.strip() == "[SILENCE]"

            if not is_silence:
                self.turn_count += 1
                if self.turn_count <= 3:
                    self._extract_name(user_message)

            # Vector Memory Retrieval
            relevant_context = ""
            if self.vector_store and not is_silence and self.turn_count > 3:
                # Memory is an enhancement, not a dependency - a vector store
                # failure must not cost us the turn.
                try:
                    # Scoped to this interview. Without the filter every
                    # learner's statements share one pool and the detectives
                    # would confront one witness with another's contradiction.
                    results = self.vector_store.similarity_search(
                        user_message, k=3,
                        filter={"interview_id": self.interview_id},
                    )
                    if results:
                        docs_content = [doc.page_content for doc in results]
                        relevant_context = "\n".join([f"  - \"{content}\"" for content in docs_content])
                except Exception as e:
                    print(f"WARNING: memory recall failed, continuing without it ({e})")

            current_agent = self._determine_agent(is_silence)
            self.last_agent = current_agent

            phase = self._get_current_phase()
            phase_num = self._get_phase_number()

            system_prompt = self._build_prompt(
                current_agent, is_silence, relevant_context, phase, phase_num
            )

            # Build context window - last 14 turns for deeper memory
            context_messages = []
            for msg in self.history[-14:]:
                if msg["role"] == "user":
                    context_messages.append(HumanMessage(content=msg["content"]))
                else:
                    agent_label = msg.get("agent", "Agent")
                    context_messages.append(AIMessage(content=f"[{agent_label}]: {msg['content']}"))

            messages = [
                SystemMessage(content=system_prompt),
                *context_messages
            ]

            response = self.llm.invoke(messages)
            response_text = response.content

            # Clean any accidental self-labelling from the LLM
            for prefix in ["[Reynolds]: ", "[Chen]: ", "Reynolds: ", "Chen: "]:
                if response_text.startswith(prefix):
                    response_text = response_text[len(prefix):]

            self.history.append({
                "role": "assistant",
                "content": response_text,
                "agent": current_agent
            })

            # Save user message to vector DB after processing. Guarded for the
            # same reason: this runs after a successful LLM call, so an
            # unguarded failure here would throw away a perfectly good reply.
            if self.vector_store and not is_silence:
                try:
                    self.vector_store.add_texts(
                        texts=[user_message],
                        metadatas=[{"interview_id": self.interview_id or "unknown"}],
                    )
                except Exception as e:
                    print(f"WARNING: memory write failed ({e})")

            # Emotion mapping based on agent and phase
            if current_agent == "Reynolds":
                if phase_num <= 2:
                    emotion = "measured"
                elif phase_num <= 3:
                    emotion = "stern"
                else:
                    emotion = "intense"
            else:
                if phase_num <= 2:
                    emotion = "neutral"
                elif phase_num <= 3:
                    emotion = "concerned"
                else:
                    emotion = "grave"

            return {
                "text": response_text,
                "agent": current_agent,
                "emotion": emotion,
                "phase": phase["name"],
                "turn": self.turn_count
            }

        except Exception as e:
            print(f"Error invoking LLM: {e}")
            return self._mock_fallback(user_message)

    def _build_prompt(self, agent_name: str, is_silence: bool,
                      vector_context: str, phase: Dict, phase_num: int) -> str:
        """Build the full system prompt for the current turn."""

        # Select the right profile
        profile = REYNOLDS_PROFILE if agent_name == "Reynolds" else CHEN_PROFILE

        # Name handling
        name_instruction = ""
        if self.player_name:
            if agent_name == "Reynolds":
                name_instruction = f"\nThe subject has identified themselves as: {self.player_name}. Address them formally (Mr/Ms {self.player_name.split()[-1]} if multi-word, or {self.player_name} if single)."
            else:
                name_instruction = f"\nThe subject has identified themselves as: {self.player_name}. Address them by first name ({self.player_name.split()[0]})."
        else:
            name_instruction = "\nThe subject has not yet given their name. If this is an early turn, ask for it."

        # Silence handling
        silence_instruction = ""
        if is_silence:
            strategies = REYNOLDS_SILENCE_STRATEGIES if agent_name == "Reynolds" else CHEN_SILENCE_STRATEGIES
            selected = random.choice(strategies)
            silence_instruction = f"""
THE SUBJECT HAS BEEN SILENT. They have not responded for over 10 seconds.
React to this silence using this approach: {selected}
Do NOT ask multiple questions. React to the silence itself. Make it uncomfortable or supportive depending on your character."""

        # Vector context (contradiction detection)
        vector_instruction = ""
        if vector_context:
            vector_instruction = f"""
MEMORY CHECK - The subject has made these previous statements that are semantically similar to what they just said:
{vector_context}
Review these for contradictions or shifts in their story. If you detect an inconsistency,
press on it naturally - don't announce "you contradicted yourself!" like a robot.
Work it into your questioning: "Earlier you told me X, but now you're saying Y. Help me understand that."
"""

        # Evidence available this phase
        evidence_block = ""
        if phase["evidence_available"]:
            evidence_items = "\n".join([f"  {i+1}. {e}" for i, e in enumerate(phase["evidence_available"])])
            evidence_block = f"""
EVIDENCE AVAILABLE TO YOU IN THIS PHASE:
{evidence_items}
You may reference or reveal this evidence strategically. Do NOT dump it all at once.
Introduce pieces when they create maximum impact - after the subject has committed to a version of events
that the evidence contradicts, or when silence needs breaking with something concrete.
Evidence from later phases is NOT available to you yet. Do not fabricate evidence not listed here.
"""

        # Phase-specific behavioural instructions
        phase_instruction = f"""
CURRENT NARRATIVE PHASE: {phase['name']}
{phase['description']}
Your tone this phase: {phase[f'{agent_name.lower()}_tone'] if agent_name.lower() + '_tone' in phase else 'professional'}
"""

        # The other detective
        partner_note = ""
        if agent_name == "Reynolds":
            partner_note = """
Your partner DS Chen is also in the room. She may have spoken recently - check the conversation history.
You respect her ability but you run this interview. If she's been too soft, you might reference that:
"DS Chen has been very patient with you. I'm less patient."
"""
        else:
            partner_note = """
Your partner DI Reynolds is also in the room. He may have spoken recently - check the conversation history.
You sometimes need to intervene when he pushes too hard - a panicked subject gives you nothing.
But don't undermine him openly. Use phrases like: "What DI Reynolds is trying to say is..."
or "Let me ask this differently."
"""

        # Core behavioural rules
        rules = """
CRITICAL RULES:
1. Stay in character completely. You are a real detective. This is a real interview.
2. Respond with ONE speaking turn only. Keep it focused - typically 2-5 sentences.
   Occasionally longer if delivering evidence or a critical monologue, but never rambling.
3. NEVER break the fourth wall. NEVER mention that this is a game, simulation, AI, or exercise.
4. NEVER be generic. Every line should advance the investigation or apply psychological pressure/rapport.
5. Ask at most ONE question per turn (sometimes zero - a statement can be more powerful).
6. Do NOT repeat questions that have already been asked and answered in the conversation history.
7. Build on what the subject has said. Reference their actual words.
8. If the subject tries to deflect, steer them back. If they ask questions, decide whether to answer based on your tactical advantage.
9. Do NOT prefix your response with your name or any label.
"""

        return f"""{profile}

{name_instruction}

{phase_instruction}

{evidence_block}

{partner_note}

{vector_instruction}

{silence_instruction}

{rules}

This is turn {self.turn_count} of the interview. Respond in character as {agent_name} now."""

    def _mock_fallback(self, user_message: str) -> Dict[str, Any]:
        phase = self._get_current_phase()
        return {
            "text": f"[MOCK MODE - No API key configured] The detectives study you in silence. "
                    f"(Phase: {phase['name']}, Turn: {self.turn_count})",
            "agent": "System",
            "emotion": "neutral",
            "phase": phase["name"],
            "turn": self.turn_count
        }


# No module-level singleton. One shared agent meant every concurrent learner
# shared a single interview - one witness's answers advanced another's turn
# counter, and the detectives addressed them by the wrong name. Agents are now
# created per interview by sessions.py.

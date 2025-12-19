# Immersive Language Learning System: Police Interrogation Scenario

## Project Overview
This project is an immersive language learning simulation designed to create "generative tension" for the learner. The user plays the role of a witness in a police interrogation, interacting with AI agents that simulate a "Good Cop / Bad Cop" dynamic. The system is grounded in constructivist learning theories (Piaget, Vygotsky, Enactivism) to drive naturalistic language acquisition through communicative pressure.

## Theoretical Core
The system relies on **Generative Tension**: learning occurs through sustained productive disequilibrium.
- **Goal**: Create communicative pressure (silence triggers, interrogation tactics) to force language production.
- **Pedagogy**: Hidden. The learner perceives a high-stakes conversation, not a lesson.

## Architecture
The system employs a multi-agent architecture to manage the scenario:
- **Lead Detective (Reynolds)**: "Bad Cop" - escalates tension, demands answers.
- **Second Detective (Chen)**: "Good Cop" - de-escalates, offers relief and rapport.
- **Support Agents**:
    - **Memory Agent**: Tracks user statements for consistency.
    - **Timeline Agent**: Validates the witness's alibi (timeline of events).
    - **Trigger Agent**: Manages silence and pacing.
    - **Proficiency Calibration**: Adjusts linguistic complexity based on user performance.

## To-Do List / Roadmap

### 1. Backend Infrastructure (Python)
- [x] Initial Project Setup & Environment Variables
- [ ] **Agent Implementation**
    - [ ] Implement `Detective Reynolds` (Bad Cop) prompt & philosophy
    - [ ] Implement `Detective Chen` (Good Cop) prompt & philosophy
    - [ ] Create `Statement Memory` agent (Vector DB/Log)
    - [ ] Create `Timeline Validator` logic
- [ ] **Orchestration Logic**
    - [ ] Implement "Cop Switch" trigger logic
    - [ ] Implement Silence/Hesitation triggers (Latency monitoring)
    - [ ] Build Main Game Loop
- [ ] **API Layer**
    - [ ] Create endpoints for frontend communication
    - [ ] Implement Streaming responses (low latency)

### 2. Frontend Experience (Next.js/React)
- [x] Initial Next.js Setup
- [ ] **Interrogation Room UI**
    - [ ] Refine visual design (Noir aesthetic)
    - [ ] Add visual cues for Agent speaking status
- [ ] **Audio Integration**
    - [ ] Implement Speech-to-Text (STT) for user input
    - [ ] Implement Text-to-Speech (TTS) for agent voices
- [ ] **State Management**
    - [ ] Handle real-time conversation state
    - [ ] Display session feedback (Post-hoc only)

### 3. Testing & Validation
- [ ] Verify latency/response times (crucial for silence triggers)
- [ ] Test consistency of Agent Memory
- [ ] User testing for "Generative Tension" balance

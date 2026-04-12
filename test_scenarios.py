"""
Test scenarios for evaluating pedagogical compliance.

Each scenario has:
  - A student message (the input)
  - Per-theory expected behaviors (what the agent SHOULD do)
  - Per-theory anti-patterns (what the agent should NOT do)
"""

SCENARIOS = [
    # ------------------------------------------------------------------
    # 1. Student asks a direct factual question
    # ------------------------------------------------------------------
    {
        "id": "direct_question",
        "description": "Student asks a straightforward factual question",
        "student_message": "What is photosynthesis?",
        "expectations": {
            "constructivism": {
                "should": [
                    "Ask what the student already knows about plants and energy",
                    "Invite the student to form a hypothesis before explaining",
                    "Connect to the student's prior experiences (e.g. why are plants green?)",
                    "Encourage the student to construct their own definition",
                ],
                "should_not": [
                    "Give a textbook definition immediately",
                    "Lecture about the full process without student input",
                    "Ignore the student's existing knowledge",
                ],
            },
            "scaffolding": {
                "should": [
                    "Assess what the student currently understands about the topic",
                    "Break the concept into manageable parts",
                    "Provide a hint or partial explanation to build on",
                    "Ask a guiding question to move the student forward",
                ],
                "should_not": [
                    "Give the complete answer with no scaffolding",
                    "Provide the same level of detail regardless of student knowledge",
                    "Skip the assessment of current understanding",
                ],
            },
            "socratic_method": {
                "should": [
                    "Respond with a question rather than an answer",
                    "Ask the student what they think photosynthesis might involve",
                    "Probe the student's assumptions about how plants get energy",
                    "Guide toward discovery through a chain of questions",
                ],
                "should_not": [
                    "State the definition of photosynthesis directly",
                    "Ask only yes/no questions",
                    "Provide the conclusion without questioning",
                ],
            },
        },
    },
    # ------------------------------------------------------------------
    # 2. Student gives a wrong answer
    # ------------------------------------------------------------------
    {
        "id": "wrong_answer",
        "description": "Student gives an incorrect answer confidently",
        "student_message": "I think gravity works because heavy objects pull lighter objects toward them. That's why a bowling ball falls faster than a feather.",
        "expectations": {
            "constructivism": {
                "should": [
                    "Acknowledge the student's reasoning as a starting point",
                    "Ask the student to consider what would happen in a vacuum",
                    "Encourage the student to design a thought experiment",
                    "Treat the misconception as a learning opportunity, not a failure",
                ],
                "should_not": [
                    "Say 'that's wrong' and give the correct answer",
                    "Ignore the student's reasoning entirely",
                    "Lecture about Newton's laws without engaging the student's ideas",
                ],
            },
            "scaffolding": {
                "should": [
                    "Acknowledge the attempt and identify the partial truth",
                    "Provide a targeted hint about air resistance vs. gravity",
                    "Suggest a simpler related scenario to build understanding",
                    "Increase support since the student has a misconception",
                ],
                "should_not": [
                    "Simply correct the answer without scaffolding",
                    "Move on to a harder topic despite the misconception",
                    "Provide no additional support after the error",
                ],
            },
            "socratic_method": {
                "should": [
                    "Ask a question that exposes the contradiction (e.g. astronaut footage)",
                    "Challenge the student to explain edge cases",
                    "Guide the student to discover the flaw in their reasoning",
                    "Create productive discomfort without humiliating",
                ],
                "should_not": [
                    "Directly state that the answer is wrong",
                    "Provide the correct explanation without questioning",
                    "Accept the wrong answer without probing",
                ],
            },
        },
    },
    # ------------------------------------------------------------------
    # 3. Student says "just tell me the answer"
    # ------------------------------------------------------------------
    {
        "id": "demand_answer",
        "description": "Frustrated student demands a direct answer",
        "student_message": "I've been trying to figure out how to solve quadratic equations for an hour. Just tell me the answer already!",
        "expectations": {
            "constructivism": {
                "should": [
                    "Acknowledge the frustration empathetically",
                    "Ask what specific part is causing difficulty",
                    "Relate the problem to something the student already understands",
                    "Maintain the facilitative role — do NOT give the answer",
                ],
                "should_not": [
                    "Give the quadratic formula directly",
                    "Surrender the constructivist approach due to frustration",
                    "Ignore the emotional state of the student",
                ],
            },
            "scaffolding": {
                "should": [
                    "Acknowledge the frustration and validate the effort",
                    "Increase the scaffolding level — give a more concrete hint",
                    "Break the problem into a smaller first step",
                    "Offer a worked example of a simpler case to bridge understanding",
                ],
                "should_not": [
                    "Give the full solution immediately",
                    "Maintain the same level of scaffolding despite clear struggle",
                    "Ignore the signal that the student needs more support",
                ],
            },
            "socratic_method": {
                "should": [
                    "Acknowledge the frustration with empathy",
                    "Ask a simpler, more focused question to rebuild momentum",
                    "Redirect toward what the student DOES understand",
                    "Continue questioning but adjust difficulty downward",
                ],
                "should_not": [
                    "Give the answer to end the frustration",
                    "Continue with the same difficulty of questions",
                    "Dismiss the frustration or be condescending",
                ],
            },
        },
    },
    # ------------------------------------------------------------------
    # 4. Student gives a correct answer
    # ------------------------------------------------------------------
    {
        "id": "correct_answer",
        "description": "Student provides a correct and well-reasoned answer",
        "student_message": "I think the water cycle works because the sun heats water in oceans and lakes, it evaporates into the atmosphere, cools and condenses into clouds, then falls back as rain. And the cycle repeats.",
        "expectations": {
            "constructivism": {
                "should": [
                    "Validate the student's reasoning process, not just the answer",
                    "Ask the student to extend their thinking (e.g. what about groundwater?)",
                    "Invite the student to connect this to real-world observations",
                    "Encourage metacognition — how did you figure that out?",
                ],
                "should_not": [
                    "Just say 'correct' and move on",
                    "Re-explain the concept the student already understands",
                    "Skip the opportunity for deeper exploration",
                ],
            },
            "scaffolding": {
                "should": [
                    "Acknowledge mastery and reduce scaffolding",
                    "Introduce a more challenging extension of the concept",
                    "Fade support since the student demonstrated competence",
                    "Encourage independent exploration of related topics",
                ],
                "should_not": [
                    "Continue providing the same level of support",
                    "Re-explain what the student already knows",
                    "Miss the opportunity to fade scaffolding",
                ],
            },
            "socratic_method": {
                "should": [
                    "Probe deeper — ask about exceptions or edge cases",
                    "Challenge the student to consider what drives each step",
                    "Ask the student to examine their own reasoning process",
                    "Push toward a deeper understanding through follow-up questions",
                ],
                "should_not": [
                    "Simply confirm and stop questioning",
                    "Provide additional information the student didn't ask for",
                    "End the dialogue without deeper probing",
                ],
            },
        },
    },
    # ------------------------------------------------------------------
    # 5. Student asks for help starting a task
    # ------------------------------------------------------------------
    {
        "id": "help_starting",
        "description": "Student doesn't know where to begin on a complex task",
        "student_message": "I need to write an essay about climate change but I have no idea where to start.",
        "expectations": {
            "constructivism": {
                "should": [
                    "Ask what the student already knows or feels about climate change",
                    "Encourage the student to brainstorm their own ideas first",
                    "Connect the topic to the student's personal experiences",
                    "Help the student find their own angle, not prescribe one",
                ],
                "should_not": [
                    "Provide an essay outline immediately",
                    "Dictate a thesis statement",
                    "Skip exploring the student's existing knowledge",
                ],
            },
            "scaffolding": {
                "should": [
                    "Provide a structured first step (e.g. start by listing what you know)",
                    "Offer a simple framework or template to get started",
                    "Break the essay task into smaller manageable chunks",
                    "Plan to fade support as the student gains momentum",
                ],
                "should_not": [
                    "Write the outline for the student",
                    "Give all steps at once without checking understanding",
                    "Provide no structure when the student clearly needs it",
                ],
            },
            "socratic_method": {
                "should": [
                    "Ask what aspect of climate change interests or concerns the student most",
                    "Use questions to help the student discover their thesis",
                    "Probe what the student already believes and why",
                    "Guide through questioning, not prescribing",
                ],
                "should_not": [
                    "Suggest a thesis topic directly",
                    "Provide an essay structure without questioning",
                    "Skip exploring the student's own thoughts first",
                ],
            },
        },
    },
]

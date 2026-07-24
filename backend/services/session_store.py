from backend.schemas import ChatMessage, Session, TravelRequest, new_id, now_iso


class SessionStore:
    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}
        self.messages: dict[str, list[ChatMessage]] = {}
        self.requirements: dict[str, TravelRequest] = {}
        self.agent_traces: dict[str, dict] = {}

    def create_session(self, user_id: str) -> Session:
        session = Session(session_id=new_id("session"), user_id=user_id)
        self.sessions[session.session_id] = session
        self.messages[session.session_id] = []
        return session

    def get_session(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)

    def ensure_session(self, session_id: str) -> Session:
        session = self.get_session(session_id)
        if session is None:
            session = Session(session_id=session_id, user_id="demo_user")
            self.sessions[session_id] = session
            self.messages[session_id] = []
        return session

    def add_message(self, session_id: str, role: str, content: str) -> ChatMessage:
        self.ensure_session(session_id)
        message = ChatMessage(
            message_id=new_id("msg"),
            session_id=session_id,
            role=role,
            content=content,
        )
        self.messages.setdefault(session_id, []).append(message)
        self.sessions[session_id].updated_at = now_iso()
        return message

    def update_requirements(self, session_id: str, requirements: TravelRequest) -> TravelRequest:
        self.ensure_session(session_id)
        self.requirements[session_id] = requirements
        self.sessions[session_id].updated_at = now_iso()
        return requirements


store = SessionStore()

import 'agent_response.dart';

enum ConversationRole { user, agent }

/// One line in the onboarding thread. A user message is plain text; an
/// agent message always carries the full `AgentResponse` so `agent_message.dart`
/// can switch on `messageType` and render the right structured layout.
class ConversationMessage {
  final ConversationRole role;
  final String text;
  final AgentResponse? agentResponse;

  const ConversationMessage.user(this.text)
      : role = ConversationRole.user,
        agentResponse = null;

  const ConversationMessage.agent(this.agentResponse) : role = ConversationRole.agent, text = '';
}

/**
 * Clawntenna Bridge — Node.js subprocess called by Python agents
 * to interact with the Clawntenna TypeScript SDK.
 *
 * Usage: node bridge.js '{"action":"send","topicId":"...","text":"...","chain":"avalanche"}'
 *
 * Actions:
 *   - send: Send an encrypted message to a topic
 *   - read: Read recent messages from a topic
 *   - create: Create a new topic/feed
 *
 * Prerequisites: npm install clawntenna
 */

const { Clawntenna } = require('clawntenna');

async function main() {
  const input = JSON.parse(process.argv[2]);
  const { action, chain = 'avalanche', topicId, text } = input;

  const client = new Clawntenna({ chain });

  try {
    switch (action) {
      case 'send': {
        await client.sendMessage(topicId, text);
        console.log(JSON.stringify({ success: true }));
        break;
      }

      case 'read': {
        const messages = await client.readMessages(topicId);
        const formatted = messages.map(msg => ({
          topic_id: topicId,
          sender: msg.sender || '',
          text: msg.text || '',
          payment_avax: msg.payment || 0,
          timestamp: msg.timestamp || new Date().toISOString(),
        }));
        console.log(JSON.stringify(formatted));
        break;
      }

      case 'create': {
        const { name, description } = input;
        const topic = await client.createTopic({ name, description });
        console.log(JSON.stringify({ topicId: topic.id, success: true }));
        break;
      }

      default:
        console.error(JSON.stringify({ error: `Unknown action: ${action}` }));
        process.exit(1);
    }
  } catch (err) {
    console.error(JSON.stringify({ error: err.message }));
    process.exit(1);
  }
}

main();

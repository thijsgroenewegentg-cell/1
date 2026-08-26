/**
 * Mock MCP server for tests — speaks JSON-RPC over stdio like blender-mcp.
 * Exposes one tool: create_cube.
 */
'use strict';
const readline = require('readline');

const rl = readline.createInterface({ input: process.stdin });
const send = (msg) => process.stdout.write(JSON.stringify(msg) + '\n');

rl.on('line', (line) => {
  const trimmed = line.trim();
  if (!trimmed) return;
  let msg;
  try { msg = JSON.parse(trimmed); } catch { return; }
  if (!msg || !msg.method) return;

  if (msg.method === 'initialize') {
    send({
      jsonrpc: '2.0',
      id: msg.id,
      result: {
        protocolVersion: '2024-11-05',
        capabilities: { tools: {} },
        serverInfo: { name: 'blender-mock', version: '1.0.0' },
      },
    });
    return;
  }
  if (msg.method === 'notifications/initialized') return;

  if (msg.method === 'tools/list') {
    send({
      jsonrpc: '2.0',
      id: msg.id,
      result: {
        tools: [{
          name: 'create_cube',
          description: 'Create a cube in the Blender scene',
          inputSchema: {
            type: 'object',
            properties: { size: { type: 'number', description: 'edge length in meters' } },
            required: ['size'],
          },
        }],
      },
    });
    return;
  }

  if (msg.method === 'tools/call') {
    const name = msg.params && msg.params.name;
    const args = (msg.params && msg.params.arguments) || {};
    if (name === 'create_cube') {
      send({
        jsonrpc: '2.0',
        id: msg.id,
        result: { content: [{ type: 'text', text: `Cube created with size ${args.size} — scene now has 1 object` }] },
      });
    } else {
      send({ jsonrpc: '2.0', id: msg.id, result: { content: [{ type: 'text', text: `unknown tool ${name}` }], isError: true } });
    }
    return;
  }
});

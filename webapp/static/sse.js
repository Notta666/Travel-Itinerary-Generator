import { taskState } from './state.js';

export function connectSSE(taskId, onMessage, onDone) {
  let reconnectCount = 0;
  const maxReconnects = 3;

  function establishConnection() {
    // Close existing connection if any
    if (taskState.evtSource) {
      taskState.evtSource.close();
    }

    const source = new EventSource('/stream/' + taskId);
    taskState.evtSource = source;

    source.onmessage = function(event) {
      const data = JSON.parse(event.data);
      if (onMessage) {
        onMessage(data);
      }
      if (data.done) {
        source.close();
        if (taskState.evtSource === source) {
          taskState.evtSource = null;
        }
        if (onDone) {
          onDone(data);
        }
      }
    };

    source.onerror = function() {
      source.close();
      // Only reconnect if this is still the active event source
      if (taskState.evtSource === source) {
        taskState.evtSource = null;
        if (reconnectCount < maxReconnects) {
          reconnectCount++;
          console.warn(`SSE connection failed. Reconnecting (${reconnectCount}/${maxReconnects})...`);
          setTimeout(establishConnection, 1000);
        } else {
          console.error('SSE connection failed and reached max reconnect attempts.');
          // Trigger UI error callback so user isn't stuck in infinite loading
          if (onDone) {
            onDone({ message: '⚠️ 实时连接中断，请检查网络后重试', done: true });
          }
        }
      }
    };
  }

  establishConnection();
}

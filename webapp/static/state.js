export class TaskState {
  constructor() {
    this.currentTaskId = null;
    this.evtSource = null;
    this.quoteTimer = null;
  }

  reset() {
    this.currentTaskId = null;
    if (this.evtSource) {
      this.evtSource.close();
      this.evtSource = null;
    }
    if (this.quoteTimer) {
      clearInterval(this.quoteTimer);
      this.quoteTimer = null;
    }
  }
}

export const taskState = new TaskState();

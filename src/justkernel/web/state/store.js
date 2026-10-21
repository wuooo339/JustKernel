import { initialState, reduce, replay, setStream } from "./reducer.js";

function createStore(initial = initialState) {
  let state = initial;
  const listeners = new Set();

  function emit() {
    for (const listener of listeners) listener(state);
  }

  return {
    getState() {
      return state;
    },
    dispatch(event) {
      state = reduce(state, event);
      emit();
      return state;
    },
    replay(events) {
      state = replay(events, state);
      emit();
      return state;
    },
    setStream(status, mode) {
      state = setStream(state, status, mode);
      emit();
      return state;
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

export { createStore };

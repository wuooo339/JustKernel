import fixture from "./fixture.json" with { type: "json" };
import { replay } from "../state/reducer.js";

const DEMO_META = Object.freeze({ ...fixture.meta });
const DEMO_EVENTS = Object.freeze(fixture.events.map((event) => Object.freeze({ ...event })));
const DEMO_STATE = replay(DEMO_EVENTS);

export { DEMO_EVENTS, DEMO_META, DEMO_STATE };

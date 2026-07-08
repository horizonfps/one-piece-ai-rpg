import { mount } from 'svelte'
import Map from './lib/Map.svelte'

// Standalone preview harness; mounts with sample defaults, no backend.
const app = mount(Map, { target: document.getElementById('map-preview') })

export default app

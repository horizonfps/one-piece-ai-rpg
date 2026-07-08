<script>
  import Start from './lib/Start.svelte'
  import Loading from './lib/Loading.svelte'
  import SetupWizard from './lib/SetupWizard.svelte'
  import Onboarding from './lib/Onboarding.svelte'
  import CharacterCreation from './lib/CharacterCreation.svelte'
  import Game from './lib/Game.svelte'
  import Settings from './lib/Settings.svelte'
  import Credits from './lib/Credits.svelte'
  import Tutorial from './lib/Tutorial.svelte'

  // Minimal phase routing, no router lib. 'repair' is the wizard with only the connection step.
  let campaignId = $state(null)
  let phase = $state('loading')
  let boot = $state(null) // {health, settings} from Loading

  // Dev deep-links skip the wizard on purpose.
  function bootDone(data) {
    boot = data
    const p = new URLSearchParams(location.search)
    const create = p.get('create')
    const play = p.get('play')
    if (create) {
      campaignId = create
      phase = 'create'
      return
    }
    if (play) {
      campaignId = play
      phase = 'game'
      return
    }
    phase = data.settings.setup_completed ? 'start' : 'wizard'
  }

  // New game routes through onboarding with no campaign yet; it's seeded only when the sheet
  // is confirmed, to avoid an orphan save if the player backs out.
  function open(id, isNew = false) {
    campaignId = id
    phase = isNew ? 'onboarding' : 'game'
  }

  function toStart() {
    campaignId = null
    phase = 'start'
  }
</script>

{#if phase === 'loading'}
  <Loading ondone={bootDone} />
{:else if phase === 'wizard'}
  <SetupWizard mode="full" health={boot?.health} oncomplete={toStart} />
{:else if phase === 'repair'}
  <SetupWizard mode="repair" health={boot?.health} oncomplete={toStart} />
{:else if phase === 'game'}
  <Game {campaignId} onback={toStart} />
{:else if phase === 'create'}
  <CharacterCreation {campaignId} onstart={(id) => open(id, false)} onback={toStart} />
{:else if phase === 'onboarding'}
  <Onboarding oncontinue={() => (phase = 'create')} onback={toStart} />
{:else if phase === 'settings'}
  <Settings onback={toStart} />
{:else if phase === 'credits'}
  <Credits onback={toStart} />
{:else if phase === 'tutorial'}
  <Tutorial onback={toStart} />
{:else}
  <Start
    onopen={open}
    onsettings={() => (phase = 'settings')}
    ontutorial={() => (phase = 'tutorial')}
    oncredits={() => (phase = 'credits')}
    onreconnect={() => (phase = 'repair')}
  />
{/if}

import os
import json
import random
import subprocess

import signpostclient as signpost

from validator import settings

def validate():
  # Get the current state.
  state = json.loads(signpost.find(settings['state']))

  # Generate a set of claimed DIDs.
  claim = set(state['meta']['claimed'].keys())

  # Get the current list of candidates.
  candi = set(json.loads(signpost.find(settings['query'],no_data=False))['dids'])

  # Find candidates not yet claimed.
  candi = claim - candi

  # Select a candidate.
  candi = random.choice(candi)

  # Update local state with a claim.
  state['meta']['claimed'][candi] = 'tmp_id'

  # Attempt to claim a candidate.
  ret = json.loads(signpost.post(state['did'],state['rev'],json.dumps(state['meta']),meta=True))
  if 'error' in ret: return # Early return - we failed to claim a candidate.

  # Pull selected candidate state.
  candi_state = json.loads(signpost.find(candi))

  # Pull data from candidate data did.
  filename = json.loads(signpost.find(candi_state['meta']['data_did'],no_data=False))['files'][0]

  # Validate data as bam format.
  valid = bool(subprocess.call(['picard-tools','ValidateSamFile',filename]))

  # Delete the file.
  os.remove(filename)

  # Update state with results of validation.
  while True:

    # Refresh state.
    state = json.loads(signpost.find(settings['state']))

    # Update local state with result.
    state['meta']['valid' if valid else 'invalid'].append(candi)

    # Attempt to push state.
    ret = json.loads(signpost.post(state['did'],state['rev'],json.dumps(state['meta']),meta=True))
    if 'error' in ret: continue # Try again until success.

    # Successfully updated state - we're done.
    return

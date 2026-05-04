# This script identifies and deletes unused definitions in a PSCAD project.
# Run from within the PSCAD scripting environment and change the project name as needed.

import mhi.pscad

pscad = mhi.pscad.application()
project = pscad.project("Solbakken")

round_num = 1
while True:
    unused = [name for name in project.definitions() 
              if project.definition(name)._instances == 0]
    
    if not unused:
        print("\nNo more unused definitions found. Done!")
        break
    
    print(f"\nRound {round_num} - found {len(unused)} unused definitions:")
    for name in unused:
        print(f"  Deleting: {name}")
        project.delete_definition(name)
    
    project.save()
    print(f"Round {round_num} complete - project saved.")
    round_num += 1



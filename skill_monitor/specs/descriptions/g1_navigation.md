The humanoid robot walks to a goal point it has been commanded to reach, in a room that
may contain obstacles, while a navigation planner chooses its path and steers it.

The skill begins when a goal has been commanded. The robot first gets going: it starts
moving and begins to close the distance to the goal; this should happen within about 15
seconds. It then walks towards the goal, steadily getting closer, for at most about 60
seconds. It finishes by arriving within half a metre of the goal.

Throughout the whole skill the robot must stay upright -- falling over is a safety
failure that must stop it at once -- and it must never come dangerously close to an
obstacle, which is also a safety failure.

While it is walking, the robot must keep getting closer to the goal. Sustained failure to
get any closer while still away from the goal means the skill has failed, even if the
planner believes it is still following its path: the robot may be stalled, slipping or
blocked.

The skill succeeds when the robot is within arrival distance of the goal and still
upright. The monitor checks the robot once per second.

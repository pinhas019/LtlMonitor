The humanoid robot fetches an object and delivers it to a drop-off station. A task
executor tells it where to walk and when to grasp and release, and a navigation planner
steers it around obstacles.

The skill begins when the task is commanded. First the robot walks to the object: it
should start getting closer to it within about 15 seconds and reach it within about 45
seconds. Then it picks the object up while standing next to it; the grasp should succeed
within about 10 seconds of arriving. Then it carries the object to the drop-off station,
getting steadily closer, within about 60 seconds; the object must stay in the robot's
gripper for the whole carry, and losing it is a failure of the task. Finally it puts the
object down at the drop-off station, which should take no more than about 10 seconds
after arriving.

Throughout the whole task the robot must stay upright -- falling is a safety failure that
must stop it at once -- and it must never come dangerously close to an obstacle, which is
also a safety failure. A sustained failure to get any closer to where it is walking,
while still away from it, means the task has failed.

The task succeeds when the object rests at the drop-off station, within half a metre of
it, and the robot is no longer holding it. The monitor checks the robot once per second.

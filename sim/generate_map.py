import json
import os
import xml.etree.ElementTree as ET
import math

def main():
    # Load config
    config_path = '/app/sim_config.json'
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            config = json.load(f)
    else:
        config = {}

    map_size_x = config.get('map_size_x', 10.0)
    map_size_y = config.get('map_size_y', 10.0)

    # Resolution (meters per pixel)
    resolution = 0.1
    width = int(map_size_x / resolution)
    height = int(map_size_y / resolution)

    # Calculate origin (bottom-left corner of the map in map coordinates)
    origin_x = -map_size_x / 2.0
    origin_y = -map_size_y / 2.0

    # Try to parse obstacles from arena.xml
    obstacles = []
    arena_path = '/app/arena.xml'
    if os.path.exists(arena_path):
        try:
            tree = ET.parse(arena_path)
            root = tree.getroot()
            for body in root.iter('body'):
                if body.get('name') == 'target':
                    continue
                pos_str = body.get('pos', '0 0 0')
                pos = [float(val) for val in pos_str.split()]
                for geom in body.iter('geom'):
                    gtype = geom.get('type')
                    size_str = geom.get('size', '0.1 0.1')
                    size = [float(val) for val in size_str.split()]
                    if gtype == 'cylinder':
                        radius = size[0]
                        obstacles.append(('cylinder', pos[0], pos[1], radius))
                    elif gtype == 'box':
                        obstacles.append(('box', pos[0], pos[1], size[0], size[1]))
                    elif gtype == 'sphere':
                        obstacles.append(('sphere', pos[0], pos[1], size[0]))
            print(f"Parsed {len(obstacles)} obstacles from {arena_path}")
        except Exception as e:
            print(f"Failed to parse arena.xml for obstacles: {e}")

    # Ensure directories exist
    os.makedirs('/app/nav2_config', exist_ok=True)

    # Write map.yaml
    with open('/app/nav2_config/map.yaml', 'w') as f:
        f.write("image: map.pgm\n")
        f.write(f"resolution: {resolution}\n")
        f.write(f"origin: [{origin_x}, {origin_y}, 0.0]\n")
        f.write("negate: 0\n")
        f.write("occupied_thresh: 0.65\n")
        f.write("free_thresh: 0.196\n")

    # Generate PGM map data
    map_data = bytearray([255] * (width * height))
    for py in range(height):
        for px in range(width):
            # Coordinate of pixel center
            x = origin_x + (px + 0.5) * resolution
            y = origin_y + (py + 0.5) * resolution
            
            # Check if inside any obstacle
            for obs in obstacles:
                if obs[0] == 'cylinder' or obs[0] == 'sphere':
                    _, ox, oy, r = obs
                    # Add a small safety margin of 1 pixel (0.1m) to prevent grazing collisions
                    if (x - ox)**2 + (y - oy)**2 <= (r + 0.05)**2:
                        map_data[py * width + px] = 0
                elif obs[0] == 'box':
                    _, ox, oy, sx, sy = obs
                    if abs(x - ox) <= (sx + 0.05) and abs(y - oy) <= (sy + 0.05):
                        map_data[py * width + px] = 0

    # Write map.pgm
    with open('/app/nav2_config/map.pgm', 'wb') as f:
        f.write(f"P5\n{width} {height}\n255\n".encode('ascii'))
        f.write(map_data)

    print(f"Generated map: {width}x{height} pixels ({map_size_x}mx{map_size_y}m) with origin [{origin_x}, {origin_y}]")

if __name__ == '__main__':
    main()

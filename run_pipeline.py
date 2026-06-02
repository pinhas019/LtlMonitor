#!/usr/bin/env python3
import argparse
import subprocess
import sys
import os
import time

def run_command(cmd: list, check: bool = True, env: dict = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, check=check, env=env)
    except subprocess.CalledProcessError as e:
        print(f"Error: Command failed: {' '.join(cmd)}", file=sys.stderr)
        sys.exit(e.returncode or 1)

def main():
    parser = argparse.ArgumentParser(description="Run the entire LTL Monitor and simulation pipeline.")
    parser.add_argument('--description', '-d', type=str, help="Natural language description of the robot skill.")
    parser.add_argument('--api-url', '--ollama-url', dest='api_url', default='http://192.168.140.111/developer-api/v1', help="API base URL (default: http://192.168.140.111/developer-api/v1).")
    parser.add_argument('--model', default='Gemma4', help="LLM model name (default: Gemma4).")
    parser.add_argument('--no-build', action='store_true', help="Skip rebuilding of Docker containers.")
    args = parser.parse_args()

    # Get skill description
    skill_desc = args.description
    if not skill_desc:
        if sys.stdin.isatty():
            print("Enter the natural language robot skill description:")
            try:
                skill_desc = input("> ").strip()
            except KeyboardInterrupt:
                print("\nExiting.")
                sys.exit(0)
        else:
            print("Error: No description provided and input is not interactive.", file=sys.stderr)
            sys.exit(1)

    if not skill_desc:
        print("Error: Skill description cannot be empty.", file=sys.stderr)
        sys.exit(1)

    # Step 1: Generate LTL formulas using the generate_formulas.py script
    print("\n" + "="*60)
    print("Step 1: Generating LTL formulas using LLM...")
    print("="*60)
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    gen_script = os.path.join(script_dir, "generate_formulas.py")
    
    gen_cmd = [
        sys.executable, gen_script,
        "-d", skill_desc,
        "--api-url", args.api_url,
        "--model", args.model
    ]
    
    run_command(gen_cmd)

    # Step 2: Restart Docker Compose stack
    print("\n" + "="*60)
    print("Step 2: Restarting Docker simulation stack...")
    print("="*60)
    
    compose_file = os.path.join(script_dir, "sim", "docker-compose.sim.yml")
    
    # Propagate model and API url to docker compose environment
    env = os.environ.copy()
    env["LLM_MODEL"] = args.model
    env["LLM_API_URL"] = args.api_url
    
    # Shut down existing services
    print("Stopping active containers...")
    run_command(["docker", "compose", "-f", compose_file, "down"], check=False, env=env)
    
    # Start up new services
    up_cmd = ["docker", "compose", "-f", compose_file, "up", "-d"]
    if not args.no_build:
        up_cmd.append("--build")
        
    print("Starting simulation stack in background...")
    run_command(up_cmd, env=env)
    
    # Step 3: Stream logs from ltl-monitor container
    print("\n" + "="*60)
    print("Step 3: Streaming LTL monitor trace logs...")
    print("Press Ctrl+C to stop streaming.")
    print("="*60 + "\n")
    
    try:
        # Start streaming logs
        subprocess.run(["docker", "compose", "-f", compose_file, "logs", "-f", "ltl-monitor", "llm-client"], env=env)
    except KeyboardInterrupt:
        print("\n\nStopping log streaming.")
        if sys.stdin.isatty():
            try:
                ans = input("Do you want to shut down the simulation stack? [y/N]: ").strip().lower()
                if ans == 'y':
                    print("\nShutting down containers...")
                    subprocess.run(["docker", "compose", "-f", compose_file, "down"], env=env)
                else:
                    print("\nStack left running in the background.")
            except KeyboardInterrupt:
                print("\nLeaving stack running.")
        else:
            print("Leaving stack running in the background.")

if __name__ == '__main__':
    main()

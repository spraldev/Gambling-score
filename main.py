import pexpect
import os
import re
from datetime import datetime
import time
from PIL import Image, ImageDraw, ImageFont
from multiprocessing import Pool, Manager, cpu_count

# Directory for images
high_score_images_dir = 'high_score_images'
os.makedirs(high_score_images_dir, exist_ok=True)

def run_game(args):
    task_id, shared_high_score, high_score_lock = args

    initial_money = 100  # Starting amount

    # Betting parameters
    base_bet_percentage = 0.3  # Start by betting 30% of the bankroll
    win_multiplier = 2.0       # Double the bet after each win
    max_bet_percentage = 0.8   # Do not bet more than 80% of the bankroll
    aggressive_threshold = 500  # Bankroll below this uses aggressive betting
    max_bet_cap = 20000        # Maximum bet amount to prevent excessive risk

    current_money = initial_money
    last_bet_result = None  # Track last bet result
    consecutive_wins = 0    # Count consecutive wins

    while True:
        try:
            # Start the Java program using pexpect with encoding
            child = pexpect.spawn('java starter', encoding='utf-8', timeout=30, codec_errors='ignore')

            while True:
                # Read the output from the Java program
                try:
                    index = child.expect([
                        r'Would you like to play the slots\? \(Yes/yes/Y/y\) : ',
                        r'You have \$(\d+)\. How much would you like to wager\? ',
                        r'(JACKPOT!.*|You won!.*|Didn\'t win this time.*)\nYou now have \$(\d+)\.',
                        r'You\'ve run out of money! Thanks for coming! Come back soon!',
                        r'Sad to see you go! You still have \$\d+ left\. Come again soon! Thanks!',
                        r'That wasn\'t quite the correct answer\. Try again\.',
                        pexpect.EOF,
                        pexpect.TIMEOUT
                    ], timeout=30)
                except (pexpect.EOF, pexpect.TIMEOUT):
                    print(f"Task {task_id}: Connection issue, restarting the game.")
                    break
                except Exception as e:
                    print(f"Task {task_id}: Exception during expect: {e}")
                    break

                # Get outputs and clean them
                before_output = child.before.strip() if child.before else ''
                after_output = child.after.strip() if child.after else ''

                if index == 0:
                    # Prompt to play
                    child.sendline('y')
                elif index == 1:
                    # Prompt for wager
                    current_money = int(child.match.group(1))

                    # Reset current bet output for this wager
                    current_bet_output = []

                    # Append the prompt to current bet output
                    if before_output:
                        current_bet_output.append(before_output)
                    if after_output:
                        current_bet_output.append(after_output)

                    # Determine wager based on Adaptive Betting Strategy
                    if current_money < aggressive_threshold:
                        # Aggressive Betting: Bet 100% of current money
                        wager = current_money
                    else:
                        if last_bet_result == 'win':
                            consecutive_wins += 1
                            # Increase bet size after each win
                            wager_percentage = min(base_bet_percentage * (win_multiplier ** consecutive_wins), max_bet_percentage)
                        else:
                            # Reset after a loss
                            consecutive_wins = 0
                            wager_percentage = base_bet_percentage

                        # Calculate wager amount
                        wager = max(int(current_money * wager_percentage), 1)
                        # Apply max bet cap
                        wager = min(wager, max_bet_cap, current_money)

                    # Ensure we don't bet more than we have
                    wager = min(wager, current_money)

                    child.sendline(f'{wager}')
                    current_bet_output.append(f'{wager}')
                elif index == 2:
                    # Game result
                    new_amount = int(child.match.group(2))
                    result_output = child.match.group(1)
                    current_money = new_amount

                    # Append game result to current bet output
                    if before_output:
                        current_bet_output.append(before_output)
                    if after_output:
                        current_bet_output.append(after_output)

                    # Update last bet result
                    if 'won' in result_output or 'JACKPOT' in result_output:
                        last_bet_result = 'win'
                    else:
                        last_bet_result = 'loss'

                    # Update shared high score
                    with high_score_lock:
                        if new_amount > shared_high_score.value:
                            shared_high_score.value = new_amount
                            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            print(f"{timestamp} - New overall high score of ${shared_high_score.value} by task {task_id}")
                            # Generate image using current bet output
                            generate_image_from_text('\n'.join(current_bet_output), shared_high_score.value)
                elif index in [3, 4]:
                    # Game over
                    print(f"Task {task_id}: Game over, restarting.")
                    break
                elif index == 5:
                    # Incorrect answer
                    child.sendline('y')
                elif index == 6:
                    # EOF
                    print(f"Task {task_id}: EOF reached, restarting.")
                    break
                elif index == 7:
                    # TIMEOUT
                    print(f"Task {task_id}: Timeout occurred, restarting.")
                    break

            # Close the child process
            child.close(force=True)
            time.sleep(0.1)

            # Reset variables for next game
            current_money = initial_money
            last_bet_result = None
            consecutive_wins = 0

            # Continue running indefinitely

        except Exception as e:
            print(f"Task {task_id}: Exception occurred: {e}")
            try:
                if child:
                    child.close(force=True)
            except:
                pass
            time.sleep(0.1)

    return

def generate_image_from_text(text, high_score):
    try:
        font_size = 14
        # Attempt to load the Menlo font
        try:
            font_path = '/System/Library/Fonts/Menlo.ttc'
            font = ImageFont.truetype(font_path, font_size)
        except IOError:
            # If Menlo font is not found, use the default font
            font = ImageFont.load_default()
            print(f"Font 'Menlo' not found. Using default font.")

        margin = 10

        # Clean text and split into lines
        cleaned_text = text.replace('\r\n', '\n').replace('\r', '\n')
        lines = cleaned_text.split('\n')
        # Remove non-printable characters from each line
        lines = [re.sub(r'[^\x20-\x7E]', '', line) for line in lines]

        if not lines or all(not line.strip() for line in lines):
            print("No text to render. Image not created.")
            return

        # Create a temporary image for size calculation
        temp_image = Image.new('RGB', (1, 1))
        temp_draw = ImageDraw.Draw(temp_image)

        # Calculate the maximum line width and total height
        max_line_width = max(temp_draw.textlength(line, font=font) for line in lines)
        image_height = font_size * len(lines) + margin * 2
        image_width = int(max_line_width) + margin * 2

        # Create the actual image with calculated size
        image = Image.new('RGB', (image_width, image_height), color='white')
        draw = ImageDraw.Draw(image)

        # Draw each line of text
        y_text = margin
        for line in lines:
            draw.text((margin, y_text), line, font=font, fill='black')
            y_text += font_size

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # Save the image with timestamp and high score in the filename
        image_filename = f'high_score_output.png'
        image_path_root = os.path.join(os.getcwd(), image_filename)
        image.save(image_path_root)
        print(f"Image saved to {image_path_root} in root directory.")

        if high_score > 10000:
            # Also save the image to the high_score_images directory
            image_filename = f'high_score_{high_score}_{timestamp}.png'
            image_path_backup = os.path.join(high_score_images_dir, image_filename)
            image.save(image_path_backup)
            print(f"Image saved to {image_path_backup} in high_score_images directory.")

    except Exception as e:
        print(f"Error during image generation: {e}")

def main():
    total_tasks = 1000  # Run 1,000 instances at once
    num_processes = min(cpu_count() * 2, total_tasks)  # Utilize available CPU cores effectively

    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Starting tasks...")

    manager = Manager()
    shared_high_score = manager.Value('i', 0)  # Shared high score variable
    high_score_lock = manager.Lock()  # Lock for synchronizing access to shared_high_score

    try:
        with Pool(processes=num_processes) as pool:
            args = [(i, shared_high_score, high_score_lock) for i in range(total_tasks)]
            pool.map(run_game, args)
    except KeyboardInterrupt:
        print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Stopping tasks...")

if __name__ == "__main__":
    main()

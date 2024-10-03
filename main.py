import pexpect
import threading
import os
import re
from datetime import datetime
import time
from PIL import Image, ImageDraw, ImageFont
import logging
from concurrent.futures import ThreadPoolExecutor

# Global high score variable and a lock for thread safety
high_score = 0
high_score_lock = threading.Lock()

# Directories for outputs and images
output_dir = 'high_score_outputs'
high_score_images_dir = 'high_score_images'
os.makedirs(output_dir, exist_ok=True)
os.makedirs(high_score_images_dir, exist_ok=True)

# Log files
log_file = 'high_score_log.txt'
detailed_log_file = 'detailed_log.txt'
log_lock = threading.Lock()

# Event to signal threads to stop
stop_event = threading.Event()

# Configure the logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(threadName)s] %(message)s',
    handlers=[
        logging.FileHandler(detailed_log_file, mode='w'),  # Overwrite the file at the beginning
        # logging.StreamHandler()  # Uncomment to also output logs to console
    ]
)
logger = logging.getLogger()

def run_java_program(thread_id):
    global high_score

    # Set thread name for logging
    threading.current_thread().name = f"Thread-{thread_id}"

    while not stop_event.is_set():
        try:
            # Start the Java program using pexpect
            child = pexpect.spawn('java starter', encoding='utf-8', timeout=30)

            while not stop_event.is_set():
                # Store output specific to the current game
                current_game_output = []

                current_money = 100  # Starting amount

                while True:
                    if stop_event.is_set():
                        # Terminate child process
                        child.close(force=True)
                        break  # Exit inner loop to restart or stop

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
                    except pexpect.EOF:
                        logger.warning("Reached EOF, restarting the game.")
                        break  # Exit inner loop to restart the game
                    except pexpect.TIMEOUT:
                        logger.warning("Timeout occurred, restarting the game.")
                        break  # Exit inner loop to restart the game

                    # Append the output to current_game_output
                    # Include both before and after texts
                    before_output = child.before.strip()
                    after_output = child.after.strip()
                    if before_output:
                        current_game_output.append(before_output)
                        # Log to detailed log
                        logger.info(f'Output: {before_output}')
                    if after_output:
                        current_game_output.append(after_output)
                        # Log to detailed log
                        logger.info(f'Output: {after_output}')

                    if index == 0:
                        # Prompt to play
                        # Reset current_game_output for the new game
                        current_game_output = [after_output]
                        # Provide 'y'
                        child.sendline('y')
                        current_game_output.append('y')
                    elif index == 1:
                        # Prompt for wager
                        match = re.search(r'You have \$(\d+)\. How much would you like to wager\? ', child.after)
                        if match:
                            current_money = int(match.group(1))
                            wager = current_money # Bet the entire amount
                            wager = max(wager, 1)
                            current_game_output.append(f'{wager}')
                            child.sendline(f'{wager}')
                    elif index == 2:
                        # Game result and updated money
                        # Extract new amount from the matched pattern
                        new_amount = int(child.match.group(2))
                        # Update high score if necessary
                        with high_score_lock:
                            try:
                                if new_amount > high_score:
                                    high_score = new_amount
                                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                                    filename = f'high_score_{high_score}_{timestamp}_thread{thread_id}.txt'
                                    filepath = os.path.join(output_dir, filename)
                                    # Save current game output to file
                                    with open(filepath, 'w') as f:
                                        f.write('\n'.join(current_game_output))
                                    # Log the high score
                                    with log_lock:
                                        with open(log_file, 'a') as log_f:
                                            log_f.write(f'{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}: New high score of ${high_score} by thread {thread_id}\n')
                                    # Print to terminal when a new high score is achieved
                                    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - New high score of ${high_score} by thread {thread_id}")
                                    # Generate an image from the current game output
                                    generate_image_from_text('\n'.join(current_game_output), high_score)
                            except Exception as e:
                                logger.error(f"Error while logging high score: {e}")
                        # Continue the game
                    elif index == 3 or index == 4:
                        # Game over messages
                        logger.info("Game over message received, restarting the game.")
                        break  # Exit inner loop to restart the game
                    elif index == 5:
                        # Incorrect answer, try again
                        child.sendline('y')
                    elif index == 6:
                        # EOF
                        logger.warning("EOF reached, restarting the game.")
                        break
                    elif index == 7:
                        # TIMEOUT
                        logger.warning("Timeout occurred, restarting the game.")
                        break

                # Ensure the child process is terminated
                child.close(force=True)

                # Wait a short time before restarting to prevent rapid looping
                time.sleep(0.1)  # Added sleep delay

            if stop_event.is_set():
                break  # Exit outer loop if stop_event is set

        except Exception as e:
            logger.error(f"Encountered an exception: {e}")

            # Ensure child process is closed
            try:
                child.close(force=True)
            except:
                pass

            # Wait a short time before restarting to prevent rapid looping
            time.sleep(0.1)

            if stop_event.is_set():
                break

    # End of function

def generate_image_from_text(text, high_score):
    import os

    try:
        # Define image size and font
        font_size = 14
        font_name = 'Menlo'  # Change as needed
        # Try to load the font, handle exception if font is not found
        try:
            font_path = '/System/Library/Fonts/Menlo.ttc'  # Update the path as necessary
            font = ImageFont.truetype(font_path, font_size)
        except IOError:
            font = ImageFont.load_default()
            # Log to detailed log
            logger.warning(f"Font 'Menlo' not found at {font_path}. Using default font.")

        margin = 10

        # Clean text and split into lines
        cleaned_text = text.replace('\r\n', '\n').replace('\r', '\n')
        lines = cleaned_text.split('\n')
        lines = [re.sub(r'[^\x20-\x7E]', '', line) for line in lines]  # Remove non-ASCII printable characters

        # Check if there is any text to render
        if not lines or all(not line.strip() for line in lines):
            # Log to detailed log
            logger.warning("No text provided or text is empty. Image not created.")
            return

        # Create a temporary image for size calculation
        temp_image = Image.new('RGB', (1, 1))
        temp_draw = ImageDraw.Draw(temp_image)

        # Calculate image size
        max_line_width = max([temp_draw.textbbox((0, 0), line, font=font)[2] for line in lines])
        image_height = font_size * len(lines) + margin * 2
        image_width = max_line_width + margin * 2

        # Create the actual image with calculated size
        image = Image.new('RGB', (image_width, image_height), color=(255, 255, 255))
        draw = ImageDraw.Draw(image)

        # Draw each line of text
        y_text = margin
        for line in lines:
            draw.text((margin, y_text), line, font=font, fill=(0, 0, 0))
            y_text += font_size

        # Save the image to the appropriate directory
        if high_score > 10000:
            # Save the image with timestamp and high score in the filename
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            image_filename = f'high_score_{high_score}_{timestamp}.png'
            image_path = os.path.join(high_score_images_dir, image_filename)
        else:
            # Save the image to the current directory with a fixed name
            image_path = os.path.join(os.getcwd(), 'high_score_output.png')

        image.save(image_path)
        # Log to detailed log
        logger.info(f"Image saved to {image_path}")

    except Exception as e:
        logger.error(f"An error occurred during image generation: {e}")

def main():
    # Overwrite logs at the beginning is handled by logging configuration

    # Clear the high score outputs directory
    for filename in os.listdir(output_dir):
        file_path = os.path.join(output_dir, filename)
        try:
            if os.path.isfile(file_path):
                os.unlink(file_path)
        except Exception as e:
            logger.error(f"Failed to delete file {file_path}: {e}")

    # Clear the high score images directory
    for filename in os.listdir(high_score_images_dir):
        file_path = os.path.join(high_score_images_dir, filename)
        try:
            if os.path.isfile(file_path):
                os.unlink(file_path)
        except Exception as e:
            logger.error(f"Failed to delete file {file_path}: {e}")

    # Overwrite high_score_log.txt
    with open(log_file, 'w'):
        pass

    # Number of worker threads to run concurrently
    num_worker_threads = 10000  # Adjust as needed
    max_threads = 10000  # Total number of threads/tasks

    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Starting threads... (Press Ctrl+C to stop)")

    with ThreadPoolExecutor(max_workers=num_worker_threads) as executor:
        futures = []
        for i in range(max_threads):
            futures.append(executor.submit(run_java_program, i))

        try:
            # Keep main thread alive
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Stopping threads...")
            stop_event.set()
            # Wait for all futures to complete
            for future in futures:
                future.cancel()
            executor.shutdown(wait=True)
            print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - All threads have completed.")
            print(f"The highest score achieved was ${high_score}.")

if __name__ == "__main__":
    main()

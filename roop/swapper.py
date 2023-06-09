import os
from tqdm import tqdm
import cv2
import insightface
import threading
import roop.globals
from roop.analyser import get_one_face, get_many_faces
import roop.state as state

FACE_SWAPPER = None
THREAD_LOCK = threading.Lock()


def get_face_swapper():
    global FACE_SWAPPER
    with THREAD_LOCK:
        if FACE_SWAPPER is None:
            model_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), '../inswapper_128.onnx')
            FACE_SWAPPER = insightface.model_zoo.get_model(model_path, providers=roop.globals.providers)
    return FACE_SWAPPER


def swap_face_in_frame(source_face, target_face, frame):
    if target_face:
        return get_face_swapper().get(frame, target_face, source_face, paste_back=True)
    return frame


def process_faces(source_face, target_frame):
    if roop.globals.many_faces:
        many_faces = get_many_faces(target_frame)
        if many_faces:
            for face in many_faces:
                target_frame = swap_face_in_frame(source_face, face, target_frame)
    else:
        face = get_one_face(target_frame)
        if face:
            target_frame = swap_face_in_frame(source_face, face, target_frame)
    return target_frame


def process_frames(source_img, frame_paths, progress=None):
    source_face = get_one_face(cv2.imread(source_img))
    for frame_path in frame_paths:
        frame = cv2.imread(frame_path)
        try:
            result = process_faces(source_face, frame)
            cv2.imwrite(frame_path, result)
            state.mark_frame_processed(frame_path)
        except Exception as exception:
            print(exception)
            pass
        if progress:
            progress.update(1)


def multi_process_frame(source_img, frame_paths, progress):
    threads = []
    num_threads = roop.globals.gpu_threads
    num_frames_per_thread = len(frame_paths) // num_threads
    remaining_frames = len(frame_paths) % num_threads
    start_index = 0
    # create threads by frames
    for _ in range(num_threads):
        end_index = start_index + num_frames_per_thread
        if remaining_frames > 0:
            end_index += 1
            remaining_frames -= 1
        thread_frame_paths = frame_paths[start_index:end_index]
        thread = threading.Thread(target=process_frames, args=(source_img, thread_frame_paths, progress))
        threads.append(thread)
        thread.start()
        start_index = end_index
    # join threads
    for thread in threads:
        thread.join()


def process_image(source_img, target_path, output_file):
    frame = cv2.imread(target_path)
    target_frame = get_one_face(frame)
    source_face = get_one_face(cv2.imread(source_img))
    result = get_face_swapper().get(frame, target_frame, source_face, paste_back=True)
    cv2.imwrite(output_file, result)


def process_video(source_path, frame_paths, mode: str):
    progress_bar_format = '{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}{postfix}]'
    total = len(frame_paths)
    with tqdm(total=total, desc='Processing', unit='frame', dynamic_ncols=True, bar_format=progress_bar_format) as progress:
        if mode == 'cpu':
            progress.set_postfix({'mode': mode, 'cores': roop.globals.cpu_cores})
            process_frames(source_path, frame_paths, progress)
        elif mode == 'gpu':
            progress.set_postfix({'mode': mode, 'threads': roop.globals.gpu_threads})
            multi_process_frame(source_path, frame_paths, progress)

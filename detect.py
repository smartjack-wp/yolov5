import argparse
import os
import platform
import shutil
import time
import re
from pathlib import Path

import cv2
import torch
import torch.backends.cudnn as cudnn
from numpy import random

import sys
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
from .models.experimental import attempt_load
from utils.datasets import LoadStreams, LoadImages
from utils.general import (
    check_img_size, non_max_suppression, apply_classifier, scale_coords,
    xyxy2xywh, plot_one_box, strip_optimizer, set_logging)
from utils.torch_utils import select_device, load_classifier, time_synchronized


def detect(opt):
    result = []
    resultNames = {}
    save_img=False
    out, source, view_img, save_txt, imgsz = \
        opt['output'], opt['source'], opt['view-img'], opt['save-txt'], opt['img-size']
    print(opt)
    maker = opt['maker']
    webcam = source.isnumeric() or source.startswith('rtsp') or source.startswith('http') or source.endswith('.txt')

    # Initialize
    set_logging()
    device = select_device(opt['device'])
    if os.path.exists(out):
        print()
        # shutil.rmtree(out)  # delete output folder
    else:
        os.makedirs(out)  # make new output folder
    half = device.type != 'cpu'  # half precision only supported on CUDA

    # Load model
    model = opt['model']
    # model = attempt_load(weights, map_location=device)  # load FP32 model
    imgsz = check_img_size(imgsz, s=model.stride.max())  # check img_size
    if half:
        model.half()  # to FP16

    # Second-stage classifier
    classify = False
    if classify:
        modelc = load_classifier(name='resnet101', n=2)  # initialize
        modelc.load_state_dict(torch.load('weights/resnet101.pt', map_location=device)['model'])  # load weights
        modelc.to(device).eval()

    # Set Dataloader
    vid_path, vid_writer = None, None
    if webcam:
        view_img = True
        cudnn.benchmark = True  # set True to speed up constant image size inference
        dataset = LoadStreams(source, img_size=imgsz)
    else:
        save_img = True

        # if maker == 'tci':
            # gray = cv2.imread(source, cv2.IMREAD_GRAYSCALE)
            # gray = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 105, 2)
            # source = 'scaled/' + source.split('/')[-1]
            # cv2.imwrite(source, gray)

        dataset = LoadImages(source, img_size=imgsz)

    # Get names and colors
    names = model.module.names if hasattr(model, 'module') else model.names
    colors = [[random.randint(0, 255) for _ in range(3)] for _ in range(len(names))]

    # Run inference
    t0 = time.time()
    img = torch.zeros((1, 3, imgsz, imgsz), device=device)  # init img
    _ = model(img.half() if half else img) if device.type != 'cpu' else None  # run once
    for path, img, im0s, vid_cap in dataset:
        img = torch.from_numpy(img).to(device)
        img = img.half() if half else img.float()  # uint8 to fp16/32
        img /= 255.0  # 0 - 255 to 0.0 - 1.0
        if img.ndimension() == 3:
            img = img.unsqueeze(0)

        # Inference
        t1 = time_synchronized()
        pred = model(img, augment=opt['augment'])[0]

        # Apply NMS
        pred = non_max_suppression(pred, opt['conf-thres'], opt['iou-thres'], classes=opt['classes'], agnostic=opt['agnostic-nms'])
        t2 = time_synchronized()

        # Apply Classifier
        if classify:
            pred = apply_classifier(pred, modelc, img, im0s)

        # Process detections
        for i, det in enumerate(pred):  # detections per image
            if webcam:  # batch_size >= 1
                p, s, im0 = path[i], '%g: ' % i, im0s[i].copy()
            else:
                p, s, im0 = path, '', im0s

            save_path = str(Path(out) / Path(p).name)
            txt_path = str(Path(out) / Path(p).stem) + ('_%g' % dataset.frame if dataset.mode == 'video' else '')
            s += '%gx%g ' % img.shape[2:]  # print string
            gn = torch.tensor(im0.shape)[[1, 0, 1, 0]]  # normalization gain whwh
            if det is not None and len(det):
                det =  torch.tensor(det)
                # Rescale boxes from img_size to im0 size
                det[:, :4] = scale_coords(img.shape[2:], det[:, :4], im0.shape).round()
                for c in det[:, -1].unique():
                    n = (det[:, -1] == c).sum()  # detections per class
                    s += '%g %ss, ' % (n, names[int(c)])  # add to string
                    # resultNames.insert(0, names[int(c)])
                    resultNames[int(c)] = names[int(c)]

                # Write results
                height, width = im0.shape[:2]
                nameIdx = 0
                for *xyxy, conf, cls in reversed(det):
                    x1 = int(xyxy[0]) - round(width / 100)
                    x2 = int(xyxy[2]) + round(width / 100)
                    y1 = int(xyxy[1]) - round(height / 140)
                    y2 = int(xyxy[3]) + round(height / 140)

                    if len(resultNames) == 1 and nameIdx >= len(resultNames):
                        labelName = resultNames[0]
                    elif nameIdx >= len(resultNames):
                        labelName = "Unknown"
                    else:
                        labelName = resultNames[int(cls)]

                    crop_img = im0[y1:y2, x1:x2]
                    crop_path = re.sub('\.(jpg|JPG|jpeg|JPEG|png|PNG)', "_{}.jpg".format(labelName), save_path)

                    if maker == 'tci':
                        crop_img = cv2.cvtColor(crop_img, cv2.COLOR_BGR2GRAY)
                        crop_img = cv2.adaptiveThreshold(crop_img, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 45, 20)
                        
                    crop_img = cv2.copyMakeBorder(crop_img, 50, 50, 50, 50, cv2.BORDER_CONSTANT, value=[255, 255, 255])
                    cv2.imwrite(crop_path, crop_img)
                    result.append({
                        'label': labelName,
                        'path': os.path.abspath(crop_path),
                        'position': {
                            'x1': x1,
                            'x2': x2,
                            'y1': y1,
                            'y2': y2
                        }
                    })
                    # result[resultNames[nameIdx]] = os.path.abspath(crop_path)
                    nameIdx += 1

                    # if save_txt:  # Write to file
                    #     xywh = (xyxy2xywh(torch.tensor(xyxy).view(1, 4)) / gn).view(-1).tolist()  # normalized xywh
                    #     with open(txt_path + '.txt', 'a') as f:
                    #         f.write(('%s ' + '%g ' * 4 + '\n') % (names[int(cls)], *xywh))  # label format

                    # if save_img or view_img:  # Add bbox to image
                        # label = '%s %.2f' % (names[int(cls)], conf)
                        # plot_one_box(xyxy, im0, label=label, color=colors[int(cls)], line_thickness=3)
            # Print time (inference + NMS)
            print('%sDone. (%.3fs)' % (s, t2 - t1))

            # Stream results
            if view_img:
                cv2.imshow(p, im0)
                if cv2.waitKey(1) == ord('q'):  # q to quit
                    raise StopIteration

            # Save results (image with detections)
            if save_img:
                if dataset.mode == 'images':
                    print()
                    # cv2.imwrite(save_path, im0)
                else:
                    if vid_path != save_path:  # new video
                        vid_path = save_path
                        if isinstance(vid_writer, cv2.VideoWriter):
                            vid_writer.release()  # release previous video writer

                        fourcc = 'mp4v'  # output video codec
                        fps = vid_cap.get(cv2.CAP_PROP_FPS)
                        w = int(vid_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                        h = int(vid_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        vid_writer = cv2.VideoWriter(save_path, cv2.VideoWriter_fourcc(*fourcc), fps, (w, h))
                    vid_writer.write(im0)

    if save_txt or save_img:
        # print('Results saved to %s' % Path(out))
        if platform.system() == 'Darwin' and not opt['update']:  # MacOS
            os.system('open ' + save_path)

    print('Done. (%.3fs)' % (time.time() - t0))
    return result


# if __name__ == '__main__':
# parser = argparse.ArgumentParser()
# parser.add_argument('--weights', nargs='+', type=str, default='yolov5s.pt', help='model.pt path(s)')
# parser.add_argument('--source', type=str, default='inference/images', help='source')  # file/folder, 0 for webcam
# parser.add_argument('--output', type=str, default='inference/output', help='output folder')  # output folder
# parser.add_argument('--img-size', type=int, default=640, help='inference size (pixels)')
# parser.add_argument('--conf-thres', type=float, default=0.4, help='object confidence threshold')
# parser.add_argument('--iou-thres', type=float, default=0.5, help='IOU threshold for NMS')
# parser.add_argument('--device', default='', help='cuda device, i.e. 0 or 0,1,2,3 or cpu')
# parser.add_argument('--view-img', action='store_true', help='display results')
# parser.add_argument('--save-txt', action='store_true', help='save results to *.txt')
# parser.add_argument('--classes', nargs='+', type=int, help='filter by class: --class 0, or --class 0 2 3')
# parser.add_argument('--agnostic-nms', action='store_true', help='class-agnostic NMS')
# parser.add_argument('--augment', action='store_true', help='augmented inference')
# parser.add_argument('--update', action='store_true', help='update all models')
# opt = parser.parse_args()
# print(opt)
def run(model, source, maker='', view_img=False, save_txt=True, classes=None, agnostic_nms=False, augment=False, update=False):
    arg = {
        # "weights" = 'yolov5s.pt'
        "model" : model
        , "source" : source
        , "output" : 'output'
        , "img-size" : 640
        , "conf-thres" : 0.4
        , "iou-thres" : 0.5
        , "device" : '0'
        , 'maker' : maker
        , "view-img" : view_img
        , "save-txt" : save_txt
        , "classes" : classes
        , "agnostic-nms" : agnostic_nms
        , "augment" : augment
        , "update" : update
    }
    
    return detect(arg)

# with torch.no_grad():
#     if opt.update:  # update all models (to fix SourceChangeWarning)
#         for opt.weights in ['yolov5s.pt', 'yolov5m.pt', 'yolov5l.pt', 'yolov5x.pt']:
#             detect()
#             strip_optimizer(opt.weights)
#     else:
#         detect()

# Namespace(agnostic_nms=False, augment=False, classes=None, 
#         conf_thres=0.4, device='', fourcc='mp4v', half=False, 
#         img_size=640, iou_thres=0.5, output='inference/output', 
#         save_txt=False, source='./inference/images/', view_img=False, 
#         weights='yolov5s.pt')

# python detect_original.py --source 0fEtgP4d.jpg --weights ./weights/AIMTR_MAKER.pt
# python detect_original.py --source /home/jkl/gh/cmlr-gateway/lib/yolov5/0fEtgP4d.jpg --weights ./weights/AIMTR_MAKER.pt